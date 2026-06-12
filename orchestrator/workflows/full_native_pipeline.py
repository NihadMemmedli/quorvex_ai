"""
Full Native Pipeline - Unified pipeline using browser at every stage.

This is the default pipeline that uses:
- Native Planner (browser exploration for planning)
- Native Generator (live browser code generation)
- Native Healer or Hybrid Healing (test_run + diagnostic tools based healing)
"""

import asyncio
import difflib
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def playwright_headed_args() -> str:
    playwright_headless = os.environ.get("PLAYWRIGHT_HEADLESS", "").lower()
    generic_headless = os.environ.get("HEADLESS", "").lower()
    if playwright_headless == "false" or generic_headless == "false":
        return " --headed --workers=1"
    return ""


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
from utils.playwright_mcp import (
    playwright_config_cli_arg,
    prepare_run_playwright_config_content,
    write_playwright_test_mcp_config,
)
from utils.progress_reporter import (
    extract_run_id_from_path,
    init_progress_reporter,
    report_progress,
)
from utils.spec_detector import SpecDetector, SpecType
from utils.test_results_parser import categorize_error
from workflows.agentic_quality import (
    FailureTriageAgent,
    StabilityVerifier,
    TestCriticAgent,
    TestDesignAgent,
    build_agentic_summary,
)
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

    def __init__(
        self,
        project_id: str = "default",
        on_tool_use: Callable[[str, dict[str, Any]], None] | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        on_task_enqueued: Callable[[str], None] | None = None,
        owner_type: str | None = None,
        owner_id: str | None = None,
        owner_label: str | None = None,
        model_tier: str | None = None,
    ):
        self.project_id = project_id
        self.on_tool_use = on_tool_use
        self.on_progress = on_progress
        self.on_task_enqueued = on_task_enqueued
        self.owner_type = owner_type
        self.owner_id = owner_id
        self.owner_label = owner_label
        self.model_tier = (
            model_tier or os.environ.get("QUORVEX_RUN_MODEL_TIER") or "tool_deep"
        )
        self._memory_run_id: str | None = None
        self.test_data_execution_context: dict[str, Any] = {}
        self.test_data_env_vars: dict[str, str] = {}
        self._load_project_credentials()
        self.native_planner = NativePlanner(
            project_id=project_id,
            on_tool_use=on_tool_use,
            on_progress=on_progress,
            on_task_enqueued=on_task_enqueued,
            owner_type=owner_type,
            owner_id=owner_id,
            owner_label=owner_label,
            model_tier=self.model_tier,
            env_vars=self.test_data_env_vars,
        )
        self.native_generator = NativeGenerator(
            on_tool_use=on_tool_use,
            on_progress=on_progress,
            on_task_enqueued=on_task_enqueued,
            owner_type=owner_type,
            owner_id=owner_id,
            owner_label=owner_label,
            model_tier=self.model_tier,
            project_id=project_id,
            env_vars=self.test_data_env_vars,
        )
        self.native_healer = NativeHealer(
            on_tool_use=on_tool_use,
            on_progress=on_progress,
            on_task_enqueued=on_task_enqueued,
            owner_type=owner_type,
            owner_id=owner_id,
            owner_label=owner_label,
            model_tier=self.model_tier,
            env_vars=self.test_data_env_vars,
        )
        self.api_generator = NativeApiGenerator()
        self.api_healer = NativeApiHealer()
        self.test_design_agent = TestDesignAgent()
        self.test_critic_agent = TestCriticAgent()
        self.failure_triage_agent = FailureTriageAgent()
        self.stability_verifier = StabilityVerifier()

    def _configure_run_agent_env(self, run_dir: Path) -> None:
        """Attach per-run artifact paths to all native agent env copies."""
        cost_log = str(run_dir / "agent_costs.jsonl")
        test_data_env_vars = getattr(self, "test_data_env_vars", None)
        if not isinstance(test_data_env_vars, dict):
            test_data_env_vars = {}
            self.test_data_env_vars = test_data_env_vars
        test_data_env_vars["AGENT_COST_LOG"] = cost_log
        for agent in (
            getattr(self, "native_planner", None),
            getattr(self, "native_generator", None),
            getattr(self, "native_healer", None),
        ):
            if agent is None:
                continue
            env_vars = getattr(agent, "env_vars", None)
            if isinstance(env_vars, dict):
                env_vars["AGENT_COST_LOG"] = cost_log

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
                logger.info(
                    f"[Credentials] Loaded {len(creds)} credential(s): {list(creds.keys())}"
                )
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
        storage_state_path: str | None = None,
        browser_auth_context: dict[str, Any] | None = None,
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
        run_dir.mkdir(parents=True, exist_ok=True)
        self._configure_run_agent_env(run_dir)
        spec_file = Path(spec_path)
        spec_content = spec_file.read_text()
        auth_context = browser_auth_context or self._load_browser_auth_context()
        if storage_state_path:
            self.prepare_run_browser_context(
                run_dir=run_dir,
                storage_state_path=storage_state_path,
            )
        raw_included_spec_content = self._resolve_includes(
            spec_content, spec_path, resolve_testdata=False
        )

        existing_test_content = ""
        if existing_test_path:
            try:
                existing_test_content = Path(existing_test_path).read_text()
            except OSError:
                existing_test_content = ""

        test_data_context = self._resolve_test_data_execution_context(
            f"{spec_content}\n\n{raw_included_spec_content}",
            generated_code=existing_test_content,
        )
        self._log_test_data_resolution_context(test_data_context)
        missing_test_data = (test_data_context or {}).get("missing") or []
        if missing_test_data:
            missing_refs = ", ".join(
                f"{item.get('ref')} ({item.get('reason') or 'not_found'})"
                for item in missing_test_data
            )
            error_msg = f"Missing required @testdata refs: {missing_refs}"
            logger.error("[TestData] %s", error_msg)
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "spec.md").write_text(spec_content)
            (run_dir / "spec_resolved.md").write_text(raw_included_spec_content)
            (run_dir / "status.txt").write_text("failed")
            self._write_pipeline_error(
                run_dir,
                error_msg,
                "test_data_resolution",
                {
                    "refs": list((test_data_context or {}).get("refs") or []),
                    "missing_test_data": missing_test_data,
                },
            )
            return {
                "success": False,
                "error": error_msg,
                "stage": "test_data_resolution",
                "missing_test_data": missing_test_data,
            }
        fixture_file = self._write_test_data_fixture_file(run_dir, test_data_context)
        self._apply_test_data_execution_context(test_data_context)
        self._log_test_data_fixture_context(test_data_context, fixture_file)

        # Extract URL from spec (resolves @include directives first)
        target_url = self._extract_url(spec_content, spec_path)
        if not target_url:
            generated_from = re.search(r"Generated from:\s*`?([^`\n]+)`?", spec_content)
            if generated_from:
                error_msg = (
                    "Generated child spec is missing a standalone target URL. "
                    f"Generated from: {generated_from.group(1).strip()}. "
                    "Regenerate or repair the child spec so it contains a URL, "
                    "for example 'Navigate to https://...'."
                )
            else:
                error_msg = "No target URL found in spec (checked includes too)"
            logger.error(error_msg)
            logger.error(
                "Note: @include templates are resolved when searching for URLs"
            )
            # Write status file so the API wrapper can update DB
            (run_dir / "status.txt").write_text("error")
            return {
                "success": False,
                "error": error_msg,
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
        logger.info(
            f"   Healing Mode: {'Hybrid (Native -> Ralph)' if hybrid_healing else 'Native Only'}"
        )

        # Initialize progress reporter for real-time UI updates
        run_id = extract_run_id_from_path(run_dir)
        self._memory_run_id = run_id
        if run_id:
            init_progress_reporter(run_id)

        # Save both original and resolved spec to run dir
        (run_dir / "spec.md").write_text(spec_content)
        (run_dir / "spec_resolved.md").write_text(resolved_spec_content)

        # Extract credentials before @testdata directives are rendered into masked markdown.
        credentials = (
            (test_data_context or {}).get("login_credentials")
            or self._extract_credentials(spec_content)
            or self._extract_credentials(resolved_spec_content)
        )
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
            logger.info(
                "   Browser steps will use page fixture, API steps will use request fixture"
            )
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
                    return {
                        "success": False,
                        "error": error_msg,
                        "stage": "healing_setup",
                    }

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
                    stability_result = await self._verify_stability_or_harden(
                        test_path=test_path,
                        run_dir=run_dir,
                        browser=browser,
                        success_stage="completed",
                        attempts=0,
                    )
                    if stability_result:
                        return stability_result
                    (run_dir / "status.txt").write_text("passed")
                    self._publish_agentic_summary(run_dir)
                    return {
                        "success": True,
                        "test_path": str(test_path),
                        "attempts": 0,
                        "stage": "completed",
                    }

                logger.error(f"Test FAILED: {result.error_summary}")
                diagnosis = self._run_failure_triage(
                    test_path=test_path,
                    run_dir=run_dir,
                    result=result,
                    design=None,
                    critic=None,
                )
                if not diagnosis.get("heal_allowed", True):
                    logger.error(
                        "Failure triage marked this failure as non-healable; skipping healing"
                    )
                    (run_dir / "status.txt").write_text("failed")
                    self._publish_agentic_summary(run_dir)
                    return {
                        "success": False,
                        "test_path": str(test_path),
                        "attempts": 0,
                        "stage": "triage_blocked_healing",
                        "diagnosis": diagnosis,
                    }

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
                        test_path=test_path,
                        run_dir=run_dir,
                        browser=browser,
                        result=result,
                        diagnosis=diagnosis,
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
            plan_path: Path | None = None
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
                    auth_context=auth_context,
                )

                if plan_path and plan_path.exists():
                    logger.info(f"Plan created: {plan_path}")
                else:
                    logger.warning(
                        "Planner didn't create a structured plan, continuing with original spec"
                    )

                # Safety-net: clean up any orphaned browsers from planner stage
                cleanup_orphaned_browsers()

            logger.info("Agentic quality: analyzing test design...")
            report_progress("planning", "Analyzing test design and flake risk...")
            design = self.test_design_agent.analyze(
                spec_content=resolved_spec_content,
                target_url=target_url,
                credentials=credentials,
                plan_path=plan_path,
                run_dir=run_dir,
            )
            design_context = self.test_design_agent.condensed_context(design)
            self._publish_agentic_summary(run_dir)

            # Stage 2: Native Generation with live browser
            logger.info("Stage 2: Native Generation (live browser)...")
            report_progress("generating", "Creating test code with live browser...")

            # Use resolved spec for generation so all included content is visible
            # But keep the original spec name for the output file
            resolved_spec_path = run_dir / "spec_resolved.md"
            original_spec_name = (
                spec_file.stem
            )  # e.g., "12-create-trip-with-minimal-information"
            test_path = await self._run_native_generator(
                spec_path=str(resolved_spec_path),
                target_url=target_url,
                output_name=original_spec_name,
                design_context=design_context,
                memory_run_id=getattr(self, "_memory_run_id", None),
                auth_context=auth_context,
                execution_credentials=credentials,
            )

            if not test_path or not test_path.exists():
                error_msg = "Native generator failed to create test file"
                (run_dir / "status.txt").write_text("error")
                self._write_pipeline_error(run_dir, error_msg, "generation")
                self._publish_agentic_summary(run_dir)
                self._attribute_memory_outcome(
                    stage="native_generator",
                    success=False,
                    outcome_status="generation_failed",
                    source_type="spec",
                    source_id=str(resolved_spec_path),
                    spec_path=str(resolved_spec_path),
                )
                return {"success": False, "error": error_msg, "stage": "generation"}

            # Validate generated test content
            try:
                gen_content = test_path.read_text()
                if len(gen_content.strip()) < 100:
                    error_msg = f"Generated test file is too small ({len(gen_content)} chars) - likely incomplete generation"
                    logger.error(error_msg)
                    (run_dir / "status.txt").write_text("error")
                    self._write_pipeline_error(
                        run_dir, error_msg, "generation_validation"
                    )
                    self._publish_agentic_summary(run_dir)
                    return {
                        "success": False,
                        "error": error_msg,
                        "stage": "generation_validation",
                    }
                if "test(" not in gen_content and "test.describe" not in gen_content:
                    logger.warning(
                        "Generated test file may be invalid - missing test() or test.describe markers. "
                        "Proceeding to execution (healer may fix it)."
                    )
            except Exception as val_err:
                logger.warning(f"Could not validate generated test: {val_err}")

            logger.info(f"Test generated: {test_path}")
            self._attribute_memory_outcome(
                stage="native_generator",
                success=True,
                outcome_status="test_generated",
                source_type="spec",
                source_id=str(resolved_spec_path),
                spec_path=str(resolved_spec_path),
                test_path=str(test_path),
            )

            logger.info("Agentic quality: reviewing generated test...")
            report_progress("generating", "Reviewing generated test for flake risks...")
            critic = self.test_critic_agent.review(
                test_path=test_path, design=design, run_dir=run_dir
            )
            self._publish_agentic_summary(run_dir)

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
                self._attribute_memory_outcome(
                    stage="native_generator",
                    success=True,
                    outcome_status="first_run_passed",
                    source_type="spec",
                    source_id=str(resolved_spec_path),
                    spec_path=str(resolved_spec_path),
                    test_path=str(test_path),
                )
                stability_result = await self._verify_stability_or_harden(
                    test_path=test_path,
                    run_dir=run_dir,
                    browser=browser,
                    success_stage="completed",
                    attempts=0,
                )
                if stability_result:
                    return stability_result
                self._record_passing_selectors(test_path)
                (run_dir / "status.txt").write_text("passed")
                self._publish_agentic_summary(run_dir)
                return {
                    "success": True,
                    "test_path": str(test_path),
                    "attempts": 0,
                    "stage": "completed",
                }

            logger.error(f"Test FAILED: {result.error_summary}")
            self._attribute_memory_outcome(
                stage="native_generator",
                success=False,
                outcome_status="first_run_failed",
                source_type="spec",
                source_id=str(resolved_spec_path),
                spec_path=str(resolved_spec_path),
                test_path=str(test_path),
            )
            diagnosis = self._run_failure_triage(
                test_path=test_path,
                run_dir=run_dir,
                result=result,
                design=design,
                critic=critic,
            )
            if not diagnosis.get("heal_allowed", True):
                logger.error(
                    "Failure triage marked this failure as non-healable; skipping healing"
                )
                (run_dir / "status.txt").write_text("failed")
                self._publish_agentic_summary(run_dir)
                return {
                    "success": False,
                    "test_path": str(test_path),
                    "attempts": 0,
                    "stage": "triage_blocked_healing",
                    "diagnosis": diagnosis,
                }

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
                    test_path=test_path,
                    run_dir=run_dir,
                    browser=browser,
                    result=result,
                    diagnosis=diagnosis,
                )

            # Safety-net: clean up any orphaned browsers from healing stage
            cleanup_orphaned_browsers()
            self._attribute_memory_outcome(
                stage="native_healer",
                success=bool(healing_result.get("success")),
                outcome_status=str(healing_result.get("stage") or "healing_completed"),
                source_type="test_file",
                source_id=str(test_path),
                test_path=str(test_path),
            )
            return healing_result

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            # Emergency cleanup on pipeline failure
            cleanup_orphaned_browsers()
            (run_dir / "status.txt").write_text("error")
            self._write_pipeline_error(run_dir, str(e), "exception")
            self._publish_agentic_summary(run_dir)
            return {"success": False, "error": str(e), "stage": "exception"}

    async def _run_native_planner(
        self,
        spec_path: str,
        run_dir: Path,
        target_url: str,
        login_url: str | None = None,
        credentials: dict[str, str] | None = None,
        auth_context: dict[str, Any] | None = None,
    ) -> Path | None:
        """Run native planner to explore the app and enhance the spec."""

        spec_file = Path(spec_path)
        spec_content = spec_file.read_text()

        # Extract test name from spec
        test_name = self._extract_test_name(spec_content)

        # Build flow context from spec
        flow_context = f"""## Test: {test_name}

### Source Spec File
{spec_file.name}

### Spec Content
{spec_content}

### Target URL
{target_url}
"""
        auth_prompt_context = self._browser_auth_prompt_context(auth_context)
        if auth_prompt_context:
            flow_context = f"{flow_context}\n{auth_prompt_context}\n"
        test_data_prompt = (self.test_data_execution_context or {}).get(
            "prompt_markdown"
        )
        if test_data_prompt:
            flow_context = f"{flow_context}\n\n{test_data_prompt}\n"

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
        self,
        spec_path: str,
        target_url: str,
        output_name: str | None = None,
        design_context: str | None = None,
        memory_run_id: str | None = None,
        auth_context: dict[str, Any] | None = None,
        execution_credentials: dict[str, str] | None = None,
    ) -> Path | None:
        """Run native generator to create test code.

        Args:
            spec_path: Path to the spec file (can be resolved spec with includes expanded)
            target_url: URL of the application to test
            output_name: Override for output test file name (without extension)
        """
        try:
            test_path = await self.native_generator.generate_test(
                spec_path=spec_path,
                target_url=target_url,
                output_name=output_name,
                design_context=design_context,
                memory_run_id=memory_run_id,
                auth_context=auth_context,
                execution_credentials=execution_credentials,
            )
            return test_path
        except Exception as e:
            logger.error(f"Native generator error: {e}")
            return None

    def _run_failure_triage(
        self,
        *,
        test_path: Path,
        run_dir: Path,
        result: TestResult,
        design: dict | None,
        critic: dict | None,
    ) -> dict:
        """Create failure_diagnosis.json and publish compact run summary."""
        report_progress("healing", "Classifying failure before healing...")
        failure_context = self._build_structured_failure_context(
            test_path=test_path, run_dir=run_dir, result=result
        )
        diagnosis = self.failure_triage_agent.diagnose(
            test_path=test_path,
            error_output=f"{result.output}\n\n{failure_context}",
            design=design,
            critic=critic,
            run_dir=run_dir,
        )
        self._publish_agentic_summary(run_dir)
        return diagnosis

    def _run_stability_gate(
        self, *, test_path: Path, run_dir: Path, browser: str
    ) -> dict | None:
        """Verify a passing test remains stable across additional reruns."""
        report_progress("testing", "Verifying test stability...")
        stability = self.stability_verifier.verify(
            test_file=str(test_path),
            output_dir=str(run_dir),
            browser=browser,
            run_test=self._run_test,
        )
        self._publish_agentic_summary(run_dir)
        if stability.get("status") == "flaky":
            logger.error("Stability verification failed; marking run as flaky/failed")
            (run_dir / "status.txt").write_text("failed")
            validation_result = {
                "status": "failed",
                "mode": "stability_verifier",
                "testFile": str(test_path),
                "browser": browser,
                "message": "Test passed initially but failed stability verification",
                "stability": stability,
            }
            (run_dir / "validation.json").write_text(
                json.dumps(validation_result, indent=2)
            )
            self._publish_agentic_summary(run_dir)
            return {
                "success": False,
                "test_path": str(test_path),
                "attempts": 0,
                "stage": "stability_failed",
            }
        return None

    async def _verify_stability_or_harden(
        self,
        *,
        test_path: Path,
        run_dir: Path,
        browser: str,
        success_stage: str,
        attempts: int,
    ) -> dict | None:
        """Run stability gate and give the healer one flake-hardening pass before failing."""
        stability_result = self._run_stability_gate(
            test_path=test_path, run_dir=run_dir, browser=browser
        )
        if not stability_result:
            return None

        report_progress(
            "healing",
            "Hardening flaky healed test before final failure...",
            healing_attempt=attempts + 1,
        )
        context = self._build_stability_failure_context(run_dir)
        try:
            fixed_code = await self.native_healer.heal_test(
                str(test_path),
                error_log=context,
                timeout_seconds=int(
                    os.environ.get("HEALER_ATTEMPT_TIMEOUT_SECONDS", "600")
                ),
                diagnosis_context=(
                    "Stability verification found this test flaky after an initial pass. "
                    "Make one targeted hardening pass for timing, selector durability, and deterministic assertions."
                ),
                memory_run_id=getattr(self, "_memory_run_id", None),
                browser=browser,
            )
        except HealerTimeoutError:
            logger.error("Flake-hardening healer timed out; keeping stability failure")
            stability_result["attempts"] = attempts
            return stability_result
        except Exception as exc:
            logger.warning(f"Flake-hardening healer failed: {exc}")
            stability_result["attempts"] = attempts
            return stability_result

        if not fixed_code:
            logger.warning("Flake-hardening healer returned no changes")
            stability_result["attempts"] = attempts
            return stability_result

        rerun = self._run_test(str(test_path), str(run_dir), browser)
        if not rerun.passed:
            logger.warning("Flake-hardening changes did not pass the immediate rerun")
            stability_result["attempts"] = attempts + 1
            return stability_result

        second_stability_result = self._run_stability_gate(
            test_path=test_path, run_dir=run_dir, browser=browser
        )
        if second_stability_result:
            second_stability_result["attempts"] = attempts + 1
            return second_stability_result

        (run_dir / "status.txt").write_text("passed")
        validation_result = {
            "status": "success",
            "mode": "native_healer_stability_hardening",
            "iterations": attempts + 1,
            "testFile": str(test_path),
            "browser": browser,
            "message": "Test passed after one flake-hardening heal attempt",
        }
        (run_dir / "validation.json").write_text(
            json.dumps(validation_result, indent=2)
        )
        self._publish_agentic_summary(run_dir)
        return {
            "success": True,
            "test_path": str(test_path),
            "attempts": attempts + 1,
            "stage": success_stage,
            "stability_hardened": True,
        }

    def _build_stability_failure_context(self, run_dir: Path) -> str:
        report = self._read_json_file(run_dir / "stability_report.json") or {}
        failed_attempts = [
            attempt
            for attempt in report.get("attempts", [])
            if not attempt.get("passed")
        ]
        lines = [
            "## Stability Failure Context",
            f"Status: {report.get('status', 'unknown')}",
            f"Total reruns: {report.get('total_runs', 0)}",
            f"Failed reruns: {report.get('failed_runs', 0)}",
        ]
        for attempt in failed_attempts[:3]:
            lines.append(
                f"- Attempt {attempt.get('attempt')}: exit={attempt.get('exit_code')} "
                f"summary={attempt.get('error_summary') or 'none'}"
            )
            if attempt.get("output_tail"):
                lines.append(f"  Output tail: {attempt.get('output_tail')}")
        return "\n".join(lines)

    def _publish_agentic_summary(self, run_dir: Path) -> dict:
        """Persist compact agentic summary locally and send it to API when available."""
        summary = build_agentic_summary(run_dir)
        try:
            (run_dir / "agentic_summary.json").write_text(json.dumps(summary, indent=2))
        except Exception as e:
            logger.warning(f"Failed to write agentic_summary.json: {e}")

        try:
            from utils.progress_reporter import get_progress_reporter

            reporter = get_progress_reporter()
            if reporter and hasattr(reporter, "report_agentic_summary"):
                reporter.report_agentic_summary(summary)
        except Exception as e:
            logger.debug(f"Agentic summary API update skipped: {e}")

        return summary

    def _load_browser_auth_context(self) -> dict[str, Any]:
        try:
            raw = os.environ.get("QUORVEX_BROWSER_AUTH_CONTEXT")
            value = json.loads(raw) if raw else {}
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _browser_auth_prompt_context(
        self, context: dict[str, Any] | None = None
    ) -> str:
        context = context or self._load_browser_auth_context()
        if not context or not context.get("storage_state_attached"):
            return ""
        session_name = (
            context.get("browser_auth_session_name")
            or context.get("browser_auth_session_id")
            or "selected session"
        )
        return (
            "## Browser Authentication Context\n"
            f"The browser starts authenticated with saved session `{session_name}`. "
            "Do not generate login steps unless the scenario explicitly tests login, logout, or authentication failure."
        )

    def _attribute_memory_outcome(
        self,
        *,
        stage: str,
        success: bool,
        outcome_status: str,
        source_type: str | None = None,
        source_id: str | None = None,
        spec_path: str | None = None,
        test_path: str | None = None,
    ) -> None:
        if os.environ.get("MEMORY_ENABLED", "true").lower() != "true":
            return
        try:
            from orchestrator.memory.effectiveness import (
                get_memory_effectiveness_service,
            )

            get_memory_effectiveness_service().attribute_outcome(
                project_id=self.project_id,
                success=success,
                outcome_status=outcome_status,
                stage=stage,
                source_type=source_type,
                source_id=source_id,
                run_id=getattr(self, "_memory_run_id", None),
                spec_path=spec_path,
                test_path=test_path,
            )
        except Exception as exc:
            logger.debug("Memory outcome attribution skipped: %s", exc)

    def _record_passing_selectors(self, test_path: Path) -> None:
        """Persist selectors from a stability-verified passing test to memory."""
        try:
            from orchestrator.memory.selector_writeback import record_passing_test_selectors

            record_passing_test_selectors(
                test_path,
                project_id=self.project_id,
                run_id=getattr(self, "_memory_run_id", None),
            )
        except Exception as exc:
            logger.debug("Selector write-back skipped: %s", exc)

    @staticmethod
    def _content_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]

    @staticmethod
    def _diff_stat(before: str, after: str) -> str:
        added = removed = 0
        for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm=""):
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
        return f"+{added} -{removed}"

    @staticmethod
    def _diff_counts(before: str, after: str) -> tuple[int, int]:
        added = removed = 0
        for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm=""):
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
        return added, removed

    @staticmethod
    def _normalized_tool_name(tool_name: str | None) -> str:
        name = str(tool_name or "")
        return name.split("__")[-1] if "__" in name else name

    @classmethod
    def _normalize_tool_calls(cls, tool_calls: list[Any] | None) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for call in tool_calls or []:
            if isinstance(call, str):
                name = call
                item: dict[str, Any] = {"name": call}
            elif isinstance(call, dict):
                name = str(call.get("name") or "")
                item = dict(call)
            else:
                name = str(getattr(call, "name", "") or "")
                item = {
                    "name": name,
                    "timestamp": getattr(call, "timestamp", None),
                    "duration_ms": getattr(call, "duration_ms", None),
                    "success": getattr(call, "success", True),
                    "error": getattr(call, "error", None),
                }
            if not name:
                continue
            item["name"] = name
            item["tool"] = cls._normalized_tool_name(name)
            normalized.append(item)
        return normalized

    @staticmethod
    def _extract_healer_output_field(output: str | None, field: str) -> str | None:
        if not output:
            return None
        pattern = rf"(?im)^\s*{re.escape(field)}\s*:\s*(.+)$"
        match = re.search(pattern, output)
        return match.group(1).strip()[:500] if match else None

    @staticmethod
    def _assertion_count(content: str) -> int:
        return len(re.findall(r"\bexpect\s*\(|\bassert\.", content or ""))

    @staticmethod
    def _is_assertion_removal_allowed(content_after: str) -> bool:
        return bool(re.search(r"\btest\.fixme\s*\(", content_after or ""))

    @staticmethod
    def _guardrail_category(category: str | None) -> str:
        value = str(category or "").lower()
        if value in {"selector_changed", "selector"}:
            return "selector"
        if value in {"timeout", "timing"}:
            return "timing"
        if value in {"auth", "test_data", "server_error", "product_bug", "connectivity", "not_found"}:
            return value
        return value or "unknown"

    def _evaluate_healer_guardrails(
        self,
        *,
        content_before: str,
        content_after: str,
        tool_calls: list[dict[str, Any]],
        error_category: str | None,
    ) -> dict[str, Any]:
        tools = [str(call.get("tool") or self._normalized_tool_name(call.get("name"))) for call in tool_calls]
        tool_set = set(tools)
        changed = content_before != content_after
        missing: list[str] = []
        category = self._guardrail_category(error_category)

        if not changed:
            missing.append("non_noop_edit")
        if changed and "test_run" not in tool_set:
            missing.append("test_run")
        if changed and tools and tools[0] != "test_run":
            missing.append("first_tool_test_run")
        if changed and category in {"selector", "timing"} and not (
            {"browser_snapshot", "browser_generate_locator"} & tool_set
        ):
            missing.append("browser_snapshot_or_browser_generate_locator")
        if changed and category in {"auth", "test_data", "server_error", "product_bug", "connectivity", "not_found"} and not (
            {"browser_network_requests", "browser_console_messages"} & tool_set
        ):
            missing.append("browser_network_requests_or_browser_console_messages")

        assertion_removed = self._assertion_count(content_after) < self._assertion_count(content_before)
        fixme_explicit = self._is_assertion_removal_allowed(content_after)
        if assertion_removed and not fixme_explicit:
            missing.append("assertion_preservation_or_explicit_test_fixme")

        added, removed = self._diff_counts(content_before, content_after)
        before_lines = max(len(content_before.splitlines()), 1)
        broad_rewrite = (added + removed) > max(80, int(before_lines * 0.4))
        evidence_tools = [
            tool
            for tool in tools
            if tool
            in {
                "test_run",
                "browser_resume",
                "browser_snapshot",
                "browser_generate_locator",
                "browser_network_requests",
                "browser_console_messages",
            }
        ]
        status = "failed" if missing else "requires_stability" if broad_rewrite else "passed"
        return {
            "guardrail_status": status,
            "missing_required_tools": missing,
            "first_tool": tools[0] if tools else None,
            "mcp_evidence_tools_used": evidence_tools,
            "used_failure_state_tool": bool({"browser_resume", "browser_snapshot"} & tool_set),
            "assertion_removed": assertion_removed,
            "test_fixme_explicit": fixme_explicit,
            "broad_rewrite": broad_rewrite,
        }

    def _emit_healer_event(
        self,
        event_type: str,
        message: str,
        *,
        payload: dict[str, Any] | None = None,
        level: str = "info",
    ) -> None:
        run_id = getattr(self, "owner_id", None)
        if not run_id:
            return
        try:
            from orchestrator.services.agent_run_events import create_agent_run_event

            create_agent_run_event(
                run_id=str(run_id),
                project_id=getattr(self, "project_id", None),
                event_type=event_type,
                message=message,
                level=level,
                payload=payload or {},
            )
        except Exception as exc:
            logger.debug("Could not emit healer agent run event %s: %s", event_type, exc)

    def _record_healing_attempt(
        self, run_dir: Path, test_path: Path, records: list[dict], record: dict
    ) -> None:
        records.append(record)
        try:
            (run_dir / "healing_attempts.json").write_text(
                json.dumps({"test_file": str(test_path), "attempts": records}, indent=2)
            )
        except OSError as exc:
            logger.debug("Could not write healing_attempts.json: %s", exc)

    @staticmethod
    def _build_attempt_context(records: list[dict]) -> str | None:
        """Condense prior healing attempts into a short prompt section so the
        healer does not repeat a fix strategy that already failed."""
        if not records:
            return None
        lines = []
        for rec in records:
            changed = (
                f"changed the test file ({rec.get('diff_stat', '?')})"
                if rec.get("changed")
                else "made no file change"
            )
            outcome = (
                "test passed"
                if rec.get("passed_after")
                else f"still failed [{rec.get('error_category', 'unknown')}]"
            )
            lines.append(f"Attempt {rec.get('attempt')}: {changed}; {outcome}.")
        last = records[-1]
        if last.get("healer_summary"):
            lines.append(f"Most recent healer summary: {last['healer_summary']}")
        failed = [r for r in records if not r.get("passed_after")]
        if (
            len(failed) >= 2
            and failed[-1].get("error_category") == failed[-2].get("error_category")
        ):
            lines.append(
                "The same failure category occurred twice. Do NOT retry the same fix strategy - "
                "change approach (e.g., re-snapshot the page and regenerate the locator instead of "
                "editing the old one)."
            )
        return "\n".join(lines)[:1500]

    async def _native_healing(
        self,
        test_path: Path,
        run_dir: Path,
        browser: str,
        result: TestResult,
        diagnosis: dict | None = None,
    ) -> dict:
        """Native healing: up to 3 attempts with test_run and diagnostic tools."""
        logger.info("Stage 4: Native Healing (up to 3 attempts)...")
        report_progress("healing", "Starting native healing...", healing_attempt=1)

        max_attempts = 3
        error_log = self._build_structured_failure_context(
            test_path=test_path, run_dir=run_dir, result=result
        )
        diagnosis_context = self.failure_triage_agent.condensed_context(diagnosis)
        failure_metadata = self._extract_failed_test_metadata(
            self._read_json_file(run_dir / "test-results.json"), test_path
        )
        current_error_category = (
            (diagnosis or {}).get("category")
            or categorize_error(result.error_summary or result.output[-2000:])
        )
        attempt_records: list[dict] = []

        for attempt in range(1, max_attempts + 1):
            logger.info(f"Healing attempt {attempt}/{max_attempts}...")
            report_progress(
                "healing",
                f"Native healing attempt {attempt}/{max_attempts}...",
                healing_attempt=attempt,
            )
            self._emit_healer_event(
                "healer_attempt_started",
                f"Native healer attempt {attempt}/{max_attempts} started.",
                payload={
                    "attempt": attempt,
                    "test_file": str(test_path),
                    "browser": browser,
                    "failed_test": failure_metadata,
                    "error_category": current_error_category,
                },
            )

            try:
                content_before = ""
                try:
                    content_before = test_path.read_text()
                except OSError:
                    pass

                fixed_code = await self.native_healer.heal_test(
                    str(test_path),
                    error_log,
                    timeout_seconds=int(
                        os.environ.get("HEALER_ATTEMPT_TIMEOUT_SECONDS", "600")
                    ),
                    diagnosis_context=diagnosis_context,
                    memory_run_id=getattr(self, "_memory_run_id", None),
                    attempt_context=self._build_attempt_context(attempt_records),
                    attempt_number=attempt,
                    browser=browser,
                    failure_metadata=failure_metadata,
                )

                content_after = fixed_code if fixed_code else content_before
                tool_calls = self._normalize_tool_calls(
                    getattr(self.native_healer, "last_tool_calls", []) or []
                )
                for tool_call in tool_calls:
                    self._emit_healer_event(
                        "healer_tool_call",
                        f"Healer used {tool_call.get('tool') or tool_call.get('name')}.",
                        payload={
                            "attempt": attempt,
                            "tool": tool_call.get("tool"),
                            "name": tool_call.get("name"),
                            "success": tool_call.get("success", True),
                        },
                    )
                guardrail = (
                    self._evaluate_healer_guardrails(
                        content_before=content_before,
                        content_after=content_after,
                        tool_calls=tool_calls,
                        error_category=current_error_category,
                    )
                    if fixed_code
                    else {
                        "guardrail_status": "not_applicable",
                        "missing_required_tools": [],
                        "first_tool": tool_calls[0].get("tool") if tool_calls else None,
                        "mcp_evidence_tools_used": [
                            call.get("tool")
                            for call in tool_calls
                            if call.get("tool")
                            in {
                                "test_run",
                                "browser_resume",
                                "browser_snapshot",
                                "browser_generate_locator",
                                "browser_network_requests",
                                "browser_console_messages",
                            }
                        ],
                        "used_failure_state_tool": any(
                            call.get("tool") in {"browser_resume", "browser_snapshot"}
                            for call in tool_calls
                        ),
                    }
                )
                evidence_path = self._write_failure_evidence_packet(
                    run_dir=run_dir,
                    test_path=test_path,
                    result=result,
                    browser=browser,
                    attempt=attempt,
                    failure_metadata=failure_metadata,
                    tool_calls=tool_calls,
                    guardrail=guardrail,
                )
                if guardrail.get("used_failure_state_tool"):
                    self._emit_healer_event(
                        "healer_failure_state_captured",
                        "Healer captured failed browser state evidence.",
                        payload={
                            "attempt": attempt,
                            "evidence_tools": guardrail.get("mcp_evidence_tools_used", []),
                            "failure_evidence_packet": evidence_path,
                        },
                    )
                attempt_record = {
                    "attempt": attempt,
                    "timestamp": datetime.now().isoformat(),
                    "content_hash_before": self._content_hash(content_before),
                    "content_hash_after": self._content_hash(content_after),
                    "changed": content_after != content_before,
                    "diff_stat": self._diff_stat(content_before, content_after),
                    "healer_summary": (
                        getattr(self.native_healer, "last_agent_output", "") or ""
                    )[-500:],
                    "tool_calls": tool_calls,
                    "first_tool": guardrail.get("first_tool"),
                    "mcp_evidence_tools_used": guardrail.get("mcp_evidence_tools_used", []),
                    "used_failure_state_tool": guardrail.get("used_failure_state_tool", False),
                    "missing_required_tools": guardrail.get("missing_required_tools", []),
                    "strategy": self._extract_healer_output_field(
                        getattr(self.native_healer, "last_agent_output", "") or "", "strategy"
                    ),
                    "root_cause": self._extract_healer_output_field(
                        getattr(self.native_healer, "last_agent_output", "") or "", "root_cause"
                    )
                    or (diagnosis or {}).get("root_cause"),
                    "changed_selectors": NativeHealer._selector_delta(content_before, content_after),
                    "guardrail_status": guardrail.get("guardrail_status"),
                    "assertion_removed": guardrail.get("assertion_removed", False),
                    "broad_rewrite": guardrail.get("broad_rewrite", False),
                    "failure_evidence_packet": evidence_path,
                }

                if guardrail.get("guardrail_status") == "failed":
                    if content_after != content_before:
                        try:
                            test_path.write_text(content_before)
                            attempt_record["reverted"] = True
                        except OSError as exc:
                            attempt_record["revert_error"] = str(exc)[:300]
                    missing = ", ".join(guardrail.get("missing_required_tools", []))
                    attempt_record.update(
                        {
                            "error_category": "guardrail_failed",
                            "error_summary": f"Healer edit rejected by evidence guardrail: {missing}"[:500],
                            "passed_after": False,
                        }
                    )
                    self._record_healing_attempt(run_dir, test_path, attempt_records, attempt_record)
                    self._emit_healer_event(
                        "healer_guardrail_failed",
                        "Healer edit rejected by evidence guardrail.",
                        level="warning",
                        payload={
                            "attempt": attempt,
                            "missing_required_tools": guardrail.get("missing_required_tools", []),
                            "failure_evidence_packet": evidence_path,
                        },
                    )
                    error_log = (
                        "## Previous Healer Edit Rejected By Guardrail\n\n"
                        f"Missing required evidence: {missing or 'unknown'}\n\n"
                        + self._build_structured_failure_context(
                            test_path=test_path,
                            run_dir=run_dir,
                            result=result,
                        )
                    )
                    continue

                if fixed_code:
                    if content_after != content_before:
                        self._emit_healer_event(
                            "healer_edit_applied",
                            "Healer edit accepted for verification.",
                            payload={
                                "attempt": attempt,
                                "diff_stat": attempt_record.get("diff_stat"),
                                "guardrail_status": attempt_record.get("guardrail_status"),
                            },
                        )
                    logger.info("Re-running healed test...")
                    result = self._run_test(str(test_path), str(run_dir), browser)

                    if result.passed:
                        attempt_record.update(
                            {"error_category": "passed", "error_summary": "", "passed_after": True}
                        )
                        self._record_healing_attempt(run_dir, test_path, attempt_records, attempt_record)
                        self._emit_healer_event(
                            "healer_verification_passed",
                            f"Healed test passed after attempt {attempt}.",
                            payload={"attempt": attempt, "test_file": str(test_path), "browser": browser},
                        )
                        logger.info(f"Healed Test PASSED (after {attempt} attempt(s))!")
                        stability_result = await self._verify_stability_or_harden(
                            test_path=test_path,
                            run_dir=run_dir,
                            browser=browser,
                            success_stage="healed",
                            attempts=attempt,
                        )
                        if stability_result:
                            return stability_result
                        self._record_passing_selectors(test_path)
                        (run_dir / "status.txt").write_text("passed")

                        validation_result = {
                            "status": "success",
                            "mode": "native_healer",
                            "iterations": attempt,
                            "testFile": str(test_path),
                            "browser": browser,
                            "message": f"Test healed after {attempt} attempts",
                        }
                        (run_dir / "validation.json").write_text(
                            json.dumps(validation_result, indent=2)
                        )
                        self._publish_agentic_summary(run_dir)

                        return {
                            "success": True,
                            "test_path": str(test_path),
                            "attempts": attempt,
                            "stage": "healed",
                        }
                    else:
                        failure_text = result.error_summary or result.output[-2000:]
                        attempt_record.update(
                            {
                                "error_category": categorize_error(failure_text),
                                "error_summary": failure_text[:500],
                                "passed_after": False,
                            }
                        )
                        self._record_healing_attempt(run_dir, test_path, attempt_records, attempt_record)
                        self._emit_healer_event(
                            "healer_verification_failed",
                            "Healer edit did not pass authoritative rerun.",
                            level="warning",
                            payload={
                                "attempt": attempt,
                                "error_category": attempt_record.get("error_category"),
                                "error_summary": attempt_record.get("error_summary"),
                            },
                        )
                        error_log = "## Failure After Previous Heal Attempt\n\n" + (
                            self._build_structured_failure_context(
                                test_path=test_path,
                                run_dir=run_dir,
                                result=result,
                            )
                        )
                        failure_metadata = self._extract_failed_test_metadata(
                            self._read_json_file(run_dir / "test-results.json"), test_path
                        )
                        current_error_category = categorize_error(failure_text)
                        if attempt < max_attempts:
                            logger.warning("Test still failing, trying again...")
                else:
                    attempt_record.update(
                        {
                            "error_category": "no_fix_produced",
                            "error_summary": "Healer returned no code",
                            "passed_after": False,
                        }
                    )
                    self._record_healing_attempt(run_dir, test_path, attempt_records, attempt_record)
                    logger.warning("Healer returned no code")

            except HealerTimeoutError:
                self._record_healing_attempt(
                    run_dir,
                    test_path,
                    attempt_records,
                    {
                        "attempt": attempt,
                        "timestamp": datetime.now().isoformat(),
                        "error_category": "healer_timeout",
                        "error_summary": "Healer agent timed out",
                        "changed": False,
                        "passed_after": False,
                    },
                )
                logger.error(
                    f"Healer timed out on attempt {attempt}/{max_attempts} - stopping retries"
                )
                break

            except Exception as e:
                self._record_healing_attempt(
                    run_dir,
                    test_path,
                    attempt_records,
                    {
                        "attempt": attempt,
                        "timestamp": datetime.now().isoformat(),
                        "error_category": "healer_error",
                        "error_summary": str(e)[:500],
                        "changed": False,
                        "passed_after": False,
                    },
                )
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
        (run_dir / "validation.json").write_text(
            json.dumps(validation_result, indent=2)
        )
        self._publish_agentic_summary(run_dir)

        return {
            "success": False,
            "test_path": str(test_path),
            "attempts": max_attempts,
            "stage": "healing_exhausted",
        }

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
                spec_path=spec_path,
                target_url=target_url,
                output_name=original_spec_name,
            )

            if not test_path or not test_path.exists():
                error_msg = "API generator failed to create test file"
                (run_dir / "status.txt").write_text("error")
                self._write_pipeline_error(run_dir, error_msg, "api_generation")
                return {
                    "success": False,
                    "error": error_msg,
                    "stage": "api_generation",
                    "test_type": "api",
                }

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
            report_progress(
                "healing", "Starting API test healing...", healing_attempt=1
            )

            max_heal_attempts = 3
            error_log = self._build_structured_failure_context(
                test_path=test_path, run_dir=run_dir, result=result
            )

            for attempt in range(1, max_heal_attempts + 1):
                logger.info(f"Healing attempt {attempt}/{max_heal_attempts}...")
                report_progress(
                    "healing",
                    f"API healing attempt {attempt}/{max_heal_attempts}...",
                    healing_attempt=attempt,
                )

                try:
                    fixed_code = await self.api_healer.heal_test(
                        str(test_path),
                        error_log,
                        spec_content,
                        failure_context=error_log,
                    )

                    if fixed_code:
                        logger.info("Re-running healed API test...")
                        result = self._run_test(str(test_path), str(run_dir), browser)

                        if result.passed:
                            logger.info(
                                f"Healed API test PASSED (after {attempt} attempt(s))!"
                            )
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
                            (run_dir / "validation.json").write_text(
                                json.dumps(validation_result, indent=2)
                            )

                            return {
                                "success": True,
                                "test_path": str(test_path),
                                "attempts": attempt,
                                "stage": "healed",
                                "test_type": "api",
                            }
                        else:
                            error_log = self._build_structured_failure_context(
                                test_path=test_path,
                                run_dir=run_dir,
                                result=result,
                            )
                            if attempt < max_heal_attempts:
                                logger.warning(
                                    "API test still failing, trying again..."
                                )
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
            (run_dir / "validation.json").write_text(
                json.dumps(validation_result, indent=2)
            )

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
            return {
                "success": False,
                "error": str(e),
                "stage": "exception",
                "test_type": "api",
            }

    async def _hybrid_healing(
        self,
        test_path: Path,
        run_dir: Path,
        browser: str,
        max_iterations: int,
        spec_path: str,
    ) -> dict:
        """Hybrid healing: Native (3) + Ralph (up to 17 more)."""
        logger.info("Stage 4: Hybrid Healing...")
        logger.info("   Phase 1: Native Healing (1-3 iterations)")
        logger.info(f"   Phase 2: Ralph Loop (4-{max_iterations} iterations)")
        report_progress(
            "healing", "Starting hybrid healing (Native + Ralph)...", healing_attempt=1
        )

        # Use RalphValidator in hybrid mode which handles both phases
        validator = RalphValidator(
            max_iterations=max_iterations, hybrid_mode=True, native_phase_iterations=3
        )

        plan_file = run_dir / "plan.json"

        result = await validator.validate_and_fix(
            test_file=str(test_path),
            output_dir=str(run_dir),
            browser=browser,
            spec_file=spec_path,
            plan_file=str(plan_file) if plan_file.exists() else None,
        )

        if result.get("status") == "success":
            stability_result = await self._verify_stability_or_harden(
                test_path=test_path,
                run_dir=run_dir,
                browser=browser,
                success_stage="healed",
                attempts=result.get("iterations", 0),
            )
            if stability_result:
                return stability_result
            (run_dir / "status.txt").write_text("passed")
            self._publish_agentic_summary(run_dir)
            return {
                "success": True,
                "test_path": str(test_path),
                "attempts": result.get("iterations", 0),
                "stage": "healed",
                "phase_succeeded": result.get("phaseSucceeded", "unknown"),
            }
        else:
            (run_dir / "status.txt").write_text("failed")
            self._publish_agentic_summary(run_dir)
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
            cmd += (
                f"npx playwright test '{test_file}' --reporter=list,html,json "
                f"--project {browser} --timeout=120000"
                f"{playwright_config_cli_arg(output_dir)}{playwright_headed_args()}"
            )

            subprocess_env = {
                key: value
                for key, value in os.environ.copy().items()
                if not key.startswith("TESTDATA_")
            }

            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes to allow for multiple tests in a file
                env={**subprocess_env, **getattr(self, "test_data_env_vars", {})},
            )

            output = result.stdout + result.stderr
            json_results = self._read_json_file(json_results_file)
            json_summary = (
                self._summarize_playwright_json(json_results) if json_results else {}
            )
            if json_summary:
                passed = result.returncode == 0 and json_summary.get("failed", 0) == 0
                error_summary = (
                    ""
                    if passed
                    else (
                        json_summary.get("error_summary")
                        or self._summarize_error(output)
                    )
                )
            else:
                passed = result.returncode == 0 and "passed" in output
                error_summary = self._summarize_error(output) if not passed else ""

            return TestResult(
                passed=passed,
                exit_code=result.returncode,
                output=output,
                error_summary=error_summary,
            )

        except subprocess.TimeoutExpired:
            return TestResult(
                passed=False,
                exit_code=-1,
                output="Test timed out after 600 seconds (10 minutes)",
                error_summary="Timeout - test suite took too long",
            )
        except Exception as e:
            return TestResult(
                passed=False, exit_code=-1, output=str(e), error_summary=str(e)[:100]
            )

    def prepare_run_browser_context(
        self,
        *,
        run_dir: Path,
        storage_state_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Prepare run-local Playwright config/MCP files for saved browser auth."""
        run_dir.mkdir(parents=True, exist_ok=True)
        project_root = Path(__file__).resolve().parent.parent.parent
        playwright_config_src = project_root / "playwright.config.ts"
        playwright_config_dst = run_dir / "playwright.config.ts"
        if playwright_config_src.exists():
            headless = not (
                os.environ.get("PLAYWRIGHT_HEADLESS", "").lower() == "false"
                or os.environ.get("HEADLESS", "").lower() == "false"
            )
            config_content = prepare_run_playwright_config_content(
                playwright_config_src.read_text(),
                base_dir=project_root,
                run_dir=run_dir,
                headless=headless,
                storage_state_path=storage_state_path,
            )
            playwright_config_dst.write_text(config_content)
            runtime = write_playwright_test_mcp_config(
                run_dir=run_dir,
                server_name="playwright-test",
                config_path=playwright_config_dst,
                headless=headless,
                storage_state_path=storage_state_path,
            )
        else:
            runtime = {}

        self.native_planner.cwd = run_dir
        self.native_planner.session_dir = run_dir
        if hasattr(self.native_generator, "cwd"):
            self.native_generator.cwd = run_dir
        if hasattr(self.native_healer, "cwd"):
            self.native_healer.cwd = run_dir
        return runtime

    def _read_json_file(self, path: Path) -> dict[str, Any] | None:
        try:
            if path.exists():
                data = json.loads(path.read_text())
                return data if isinstance(data, dict) else None
        except Exception as exc:
            logger.debug(f"Could not read JSON artifact {path}: {exc}")
        return None

    def _summarize_playwright_json(self, data: dict[str, Any] | None) -> dict[str, Any]:
        """Extract pass/fail/error details from Playwright JSON reporter output."""
        if not data:
            return {}

        failed = 0
        passed = 0
        skipped = 0
        errors: list[str] = []

        def visit(node: Any) -> None:
            nonlocal failed, passed, skipped
            if isinstance(node, dict):
                status = str(node.get("status") or "").lower()
                if status in {"failed", "timedout", "interrupted", "unexpected"}:
                    failed += 1
                elif status in {"passed", "expected"}:
                    passed += 1
                elif status in {"skipped"}:
                    skipped += 1

                error = node.get("error")
                if isinstance(error, dict):
                    message = error.get("message") or error.get("value")
                    if message:
                        errors.append(str(message))
                for item in node.get("errors") or []:
                    if isinstance(item, dict):
                        message = item.get("message") or item.get("value")
                        if message:
                            errors.append(str(message))
                    elif item:
                        errors.append(str(item))
                for key in ("suites", "specs", "tests", "results"):
                    for child in node.get(key) or []:
                        visit(child)
            elif isinstance(node, list):
                for child in node:
                    visit(child)

        visit(data)
        top_status = str(data.get("status") or "").lower()
        if top_status in {"failed", "timedout", "interrupted"} and failed == 0:
            failed = 1
        return {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "status": top_status,
            "error_summary": (errors[0].splitlines()[0][:200] if errors else ""),
            "errors": errors[:5],
        }

    def _extract_failed_test_metadata(self, data: dict[str, Any] | None, fallback_file: Path | None = None) -> dict[str, Any]:
        """Extract the first failed Playwright test with enough detail for scoped healer reruns."""
        if not data:
            return {}

        failures: list[dict[str, Any]] = []

        def error_message(error: Any) -> str:
            if isinstance(error, dict):
                return str(error.get("message") or error.get("value") or error.get("stack") or "")
            return str(error or "")

        def visit_suite(suite: dict[str, Any], parent_titles: list[str]) -> None:
            suite_title = suite.get("title")
            titles = parent_titles + ([str(suite_title)] if suite_title else [])
            for spec in suite.get("specs") or []:
                if not isinstance(spec, dict):
                    continue
                spec_title = str(spec.get("title") or "Unknown test")
                full_title = " > ".join(titles + [spec_title]) if titles else spec_title
                spec_file = spec.get("file") or (str(fallback_file) if fallback_file else None)
                for test_entry in spec.get("tests") or []:
                    if not isinstance(test_entry, dict):
                        continue
                    results = [r for r in (test_entry.get("results") or []) if isinstance(r, dict)]
                    if not results:
                        continue
                    final = results[-1]
                    status = str(final.get("status") or "").lower()
                    if status not in {"failed", "timedout", "interrupted", "unexpected"}:
                        continue
                    errors = []
                    if final.get("error"):
                        errors.append(error_message(final.get("error")))
                    for item in final.get("errors") or []:
                        errors.append(error_message(item))
                    primary_error = next((item for item in errors if item), "")
                    failures.append(
                        {
                            "title": spec_title,
                            "full_title": full_title,
                            "file": spec_file,
                            "project": test_entry.get("projectName") or test_entry.get("projectId"),
                            "retry": final.get("retry", len(results) - 1),
                            "status": status,
                            "primary_error": primary_error.splitlines()[0][:500] if primary_error else "",
                            "location": {
                                "line": spec.get("line"),
                                "column": spec.get("column"),
                            },
                        }
                    )
            for child in suite.get("suites") or []:
                if isinstance(child, dict):
                    visit_suite(child, titles)

        for suite in data.get("suites") or []:
            if isinstance(suite, dict):
                visit_suite(suite, [])

        return failures[0] if failures else {}

    def _failure_evidence_packet(
        self,
        *,
        test_path: Path,
        run_dir: Path,
        result: TestResult,
        browser: str,
        attempt: int,
        failure_metadata: dict[str, Any] | None,
        tool_calls: list[dict[str, Any]] | None = None,
        guardrail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        json_results = self._read_json_file(run_dir / "test-results.json")
        metadata = failure_metadata or self._extract_failed_test_metadata(json_results, test_path)
        error_contexts = []
        for path in sorted((run_dir / "test-results").glob("**/error-context.md"))[:3]:
            if path.exists():
                error_contexts.append({"path": str(path), "excerpt": path.read_text(errors="ignore")[:2000]})
        normalized_tool_calls = self._normalize_tool_calls(tool_calls)
        return {
            "schema_version": 1,
            "attempt": attempt,
            "created_at": datetime.now().isoformat(),
            "test_file": str(test_path),
            "browser": browser,
            "failed_test": metadata,
            "exit_code": result.exit_code,
            "error_summary": result.error_summary,
            "code_frame": self._extract_code_frame(test_path, result.output),
            "attachments": self._collect_playwright_attachments(run_dir, json_results)[:20],
            "error_contexts": error_contexts,
            "stdout_stderr_tail": (result.output or "")[-6000:],
            "mcp_evidence": {
                "tool_calls": normalized_tool_calls,
                "first_tool": (guardrail or {}).get("first_tool"),
                "evidence_tools_used": (guardrail or {}).get("mcp_evidence_tools_used", []),
                "used_failure_state_tool": (guardrail or {}).get("used_failure_state_tool", False),
                "missing_required_tools": (guardrail or {}).get("missing_required_tools", []),
            },
        }

    def _write_failure_evidence_packet(
        self,
        *,
        run_dir: Path,
        test_path: Path,
        result: TestResult,
        browser: str,
        attempt: int,
        failure_metadata: dict[str, Any] | None,
        tool_calls: list[dict[str, Any]] | None = None,
        guardrail: dict[str, Any] | None = None,
    ) -> str | None:
        packet = self._failure_evidence_packet(
            test_path=test_path,
            run_dir=run_dir,
            result=result,
            browser=browser,
            attempt=attempt,
            failure_metadata=failure_metadata,
            tool_calls=tool_calls,
            guardrail=guardrail,
        )
        path = run_dir / f"failure_evidence_packet_attempt_{attempt}.json"
        try:
            path.write_text(json.dumps(packet, indent=2))
            (run_dir / "failure_evidence_packet.json").write_text(json.dumps(packet, indent=2))
            return str(path)
        except OSError as exc:
            logger.debug("Could not write failure evidence packet: %s", exc)
            return None

    def _build_structured_failure_context(
        self, *, test_path: Path, run_dir: Path, result: TestResult
    ) -> str:
        """Build compact healer context from Playwright JSON, output tails, code frame, and attachments."""
        json_results = self._read_json_file(run_dir / "test-results.json")
        summary = self._summarize_playwright_json(json_results) if json_results else {}
        failed_test = self._extract_failed_test_metadata(json_results, test_path)
        attachments = self._collect_playwright_attachments(run_dir, json_results)
        code_frame = self._extract_code_frame(test_path, result.output)
        error_contexts = [
            f"{path}: {path.read_text(errors='ignore')[:2000]}"
            for path in sorted((run_dir / "test-results").glob("**/error-context.md"))[
                :3
            ]
            if path.exists()
        ]
        sections = [
            "## Structured Failure Context",
            f"Test file: {test_path}",
            f"Exit code: {result.exit_code}",
            f"Error summary: {result.error_summary or 'unknown'}",
        ]
        if summary:
            sections.append(
                "Playwright JSON summary: "
                + json.dumps(
                    {
                        "status": summary.get("status"),
                        "passed": summary.get("passed"),
                        "failed": summary.get("failed"),
                        "skipped": summary.get("skipped"),
                        "errors": summary.get("errors"),
                    },
                    indent=2,
                )
            )
        if failed_test:
            sections.append("Failed test metadata: " + json.dumps(failed_test, indent=2))
        if code_frame:
            sections.append(f"Code frame:\n```typescript\n{code_frame}\n```")
        if attachments:
            sections.append(
                "Attachments:\n" + "\n".join(f"- {item}" for item in attachments[:10])
            )
        if error_contexts:
            sections.append("Error context files:\n" + "\n\n".join(error_contexts))
        stdout_tail = result.output[-6000:] if result.output else ""
        if stdout_tail:
            sections.append(f"Stdout/stderr tail:\n```\n{stdout_tail}\n```")
        return "\n\n".join(sections)

    def _collect_playwright_attachments(
        self, run_dir: Path, json_results: dict[str, Any] | None
    ) -> list[str]:
        attachments: list[str] = []

        def visit(node: Any) -> None:
            if isinstance(node, dict):
                for attachment in node.get("attachments") or []:
                    if not isinstance(attachment, dict):
                        continue
                    name = attachment.get("name") or "attachment"
                    path = attachment.get("path")
                    content_type = attachment.get("contentType") or attachment.get(
                        "content_type"
                    )
                    attachments.append(
                        f"{name} ({content_type or 'unknown'}): {path or 'inline'}"
                    )
                for key in ("suites", "specs", "tests", "results"):
                    for child in node.get(key) or []:
                        visit(child)
            elif isinstance(node, list):
                for child in node:
                    visit(child)

        visit(json_results or {})
        for path in sorted((run_dir / "test-results").glob("**/*"))[:50]:
            if path.is_file() and path.name != "error-context.md":
                attachments.append(str(path))
        return attachments

    def _extract_code_frame(self, test_path: Path, output: str) -> str:
        if not test_path.exists():
            return ""
        line_no = None
        match = re.search(rf"{re.escape(str(test_path))}:(\d+):\d+", output or "")
        if not match:
            match = re.search(r":(\d+):\d+\)?", output or "")
        if match:
            try:
                line_no = int(match.group(1))
            except ValueError:
                line_no = None
        try:
            lines = test_path.read_text().splitlines()
        except Exception:
            return ""
        if line_no is None:
            return "\n".join(lines[:80])
        start = max(line_no - 4, 1)
        end = min(line_no + 4, len(lines))
        return "\n".join(f"{idx}: {lines[idx - 1]}" for idx in range(start, end + 1))

    def _resolve_includes(
        self,
        content: str,
        spec_path: str = None,
        *,
        resolve_testdata: bool = True,
    ) -> str:
        """
        Resolve @include and @testdata directives in spec content.
        Returns the expanded content with all includes resolved.
        """
        if resolve_testdata:
            try:
                from sqlmodel import Session

                from orchestrator.api.db import engine
                from orchestrator.services.test_data_resolver import (
                    resolve_testdata_in_markdown,
                )

                with Session(engine) as session:
                    content = resolve_testdata_in_markdown(
                        content,
                        session=session,
                        project_id=self.project_id or "default",
                    )
            except Exception as exc:
                logger.warning("Failed to resolve @testdata directives: %s", exc)

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
                    resolved_template = self._resolve_includes(
                        template_content,
                        str(target_file),
                        resolve_testdata=resolve_testdata,
                    )
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
        resolved_content = self._resolve_includes(
            spec_content, spec_path, resolve_testdata=False
        )

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
            for login_path in [
                "/login",
                "/signin",
                "/sign_in",
                "/users/sign_in",
                "/auth/login",
            ]:
                return f"{parsed.scheme}://{parsed.netloc}{login_path}"

        return None

    def _extract_credentials(self, spec_content: str) -> dict[str, str] | None:
        """Extract credential placeholders from spec."""
        testdata_credentials = self._extract_testdata_credentials(spec_content)
        if testdata_credentials:
            return testdata_credentials

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

    def _resolve_test_data_execution_context(
        self, spec_content: str, generated_code: str | None = None
    ) -> dict[str, Any]:
        try:
            from sqlmodel import Session

            from orchestrator.api.db import engine
            from orchestrator.services.test_data_resolver import (
                resolve_test_data_execution_context,
            )

            explicit_refs: list[str] = []
            raw_refs = os.environ.get("QUORVEX_TEST_DATA_REFS", "")
            if raw_refs:
                try:
                    parsed_refs = json.loads(raw_refs)
                    if isinstance(parsed_refs, list):
                        explicit_refs = [str(ref) for ref in parsed_refs]
                except json.JSONDecodeError:
                    explicit_refs = [ref.strip() for ref in raw_refs.split(",") if ref.strip()]

            with Session(engine) as session:
                return resolve_test_data_execution_context(
                    session,
                    project_id=self.project_id or "default",
                    refs=explicit_refs,
                    markdown=spec_content,
                    generated_code=generated_code,
                )
        except Exception as exc:
            logger.warning("[Credentials] Failed to resolve execution test data: %s", exc)
            return {}

    def _apply_test_data_execution_context(self, context: dict[str, Any] | None) -> None:
        self.test_data_execution_context = context or {}
        fixture_file = self.test_data_execution_context.get("runtime_fixture_file")
        self.test_data_env_vars = (
            {"QUORVEX_TEST_DATA_FILE": str(fixture_file)} if fixture_file else {}
        )
        for component in (
            getattr(self, "native_planner", None),
            getattr(self, "native_generator", None),
            getattr(self, "native_healer", None),
        ):
            if hasattr(component, "env_vars"):
                component.env_vars = dict(self.test_data_env_vars)

    def _write_test_data_fixture_file(
        self, run_dir: Path, context: dict[str, Any] | None
    ) -> Path | None:
        fixtures = (context or {}).get("runtime_fixtures") or {}
        if not fixtures:
            return None
        fixture_dir = run_dir / "test-data"
        fixture_dir.mkdir(parents=True, exist_ok=True)
        fixture_file = fixture_dir / "resolved-fixtures.json"
        payload = {
            "project_id": self.project_id or "default",
            "refs": list((context or {}).get("refs") or []),
            "items": fixtures,
        }
        fixture_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        try:
            os.chmod(fixture_file, 0o600)
        except OSError as exc:
            logger.debug("Could not restrict test data fixture permissions: %s", exc)
        if context is not None:
            context["runtime_fixture_file"] = str(fixture_file.resolve())
        return fixture_file

    def _log_test_data_resolution_context(self, context: dict[str, Any] | None) -> None:
        refs = [str(item) for item in (context or {}).get("refs") or [] if item]
        missing = [
            f"{item.get('ref')} ({item.get('reason') or 'not_found'})"
            for item in (context or {}).get("missing") or []
            if isinstance(item, dict) and item.get("ref")
        ]
        resolved_count = len((context or {}).get("runtime_fixtures") or {})
        logger.info(
            "[TestData] refs=%s resolved_count=%s missing=%s",
            refs or [],
            resolved_count,
            missing or [],
        )

    def _log_test_data_fixture_context(
        self, context: dict[str, Any] | None, fixture_file: Path | None
    ) -> None:
        refs = [str(item) for item in (context or {}).get("refs") or [] if item]
        if not refs and not fixture_file:
            return
        injected = "QUORVEX_TEST_DATA_FILE" in self.test_data_env_vars
        logger.info(
            "[TestData] fixture_file=%s refs=%s env_injected=%s",
            str(fixture_file.resolve()) if fixture_file else None,
            refs,
            injected,
        )

    def _extract_testdata_credentials(self, spec_content: str) -> dict[str, str] | None:
        """Extract login credentials from @testdata refs and expose them as transient env vars."""
        try:
            from orchestrator.services.test_data_resolver import (
                extract_test_data_refs_from_markdown,
            )

            refs = extract_test_data_refs_from_markdown(spec_content)
            if not refs:
                return None
            context = self._resolve_test_data_execution_context(spec_content)
            self._apply_test_data_execution_context(context)
            credentials = context.get("login_credentials")
            if not credentials:
                return None
            logger.info(
                "[Credentials] Loaded login credentials from test data ref %s for runtime fixture context (legacy placeholders: %s)",
                credentials.get("test_data_ref"),
                list((context.get("env_vars") or {}).keys()),
            )
            return credentials
        except Exception as exc:
            logger.warning(
                "[Credentials] Failed to resolve @testdata login credentials: %s", exc
            )
            return None

    def _extract_test_name(self, spec_content: str) -> str:
        """Extract test name from spec."""
        # Look for # Test: or # Title: pattern
        for line in spec_content.split("\n"):
            if line.startswith("# "):
                name = line[2:].strip()
                name = name.replace("Test:", "").strip()
                return name

        return "Unnamed Test"

    def _write_pipeline_error(
        self,
        run_dir: Path,
        error: str,
        stage: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Write pipeline_error.json so the API wrapper can populate DB error_message."""
        try:
            error_data = {
                "error": error[:2000],
                "stage": stage,
                "timestamp": datetime.now().isoformat(),
            }
            if extra:
                error_data.update(extra)
            # Include the tail of long errors so the root cause (often at the end) is visible
            if len(error) > 2000:
                error_data["error_tail"] = error[-500:]
            (run_dir / "pipeline_error.json").write_text(
                json.dumps(error_data, indent=2)
            )
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
    parser.add_argument(
        "--browser", default="chromium", choices=["chromium", "firefox", "webkit"]
    )
    parser.add_argument("--hybrid", action="store_true", help="Use hybrid healing mode")
    parser.add_argument("--max-iterations", type=int, default=20)
    parser.add_argument(
        "--existing-test", help="Existing test file to heal (skips planning/generation)"
    )
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
