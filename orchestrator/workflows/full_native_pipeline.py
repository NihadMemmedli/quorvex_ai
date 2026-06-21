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

from orchestrator.services.handoff_manifest import (
    init_manifest,
    load_manifest,
    record_artifact,
    record_attempt,
    record_consumption,
    record_stage,
    validate_artifact,
)
from utils.agent_runner import AgentRunner, build_allowed_tools
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
from utils.text_utils import truncate_middle
from utils.token_budget import context_budget_for_stage, truncate_text_to_tokens
from workflows.agentic_quality import (
    FailureTriageAgent,
    StabilityVerifier,
    TestCriticAgent,
    TestDesignAgent,
    build_agentic_summary,
    extract_plan_selectors,
)
from workflows.native_api_generator import NativeApiGenerator
from workflows.native_api_healer import NativeApiHealer
from workflows.native_generator import NativeGenerator
from workflows.native_healer import HealerTimeoutError, NativeHealer
from workflows.native_planner import NativePlanner, SpecGenerationError
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
        self._last_native_generator_exception: str | None = None
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
        self.generated_preflight_list_enabled = (
            os.environ.get("QUORVEX_GENERATED_PREFLIGHT_LIST", "1").lower()
            not in {"0", "false", "no"}
        )

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

    async def _debug_validate_planner_draft_script(
        self,
        *,
        draft_path: Path,
        run_dir: Path,
        browser: str,
    ) -> dict[str, Any]:
        """Run test_debug on the planner draft before generator handoff."""
        if not draft_path.exists():
            return {"attempted": False, "status": "missing", "path": str(draft_path)}

        prompt = f"""Run `test_debug` on this planner draft Playwright script before generator handoff.

Test path: {draft_path}
Browser/project: {browser}

Rules:
- Call `test_debug` for exactly this file and browser/project.
- Do not edit files.
- Do not run unrelated tests.
- If it fails, keep the paused browser state open long enough to inspect the failure summary needed for handoff metadata.
- Do not call `browser_close`; the orchestrator owns cleanup after validation.
- Use `browser_snapshot`, console/network diagnostics, locator generation, or `browser_resume` only when needed to summarize the failed paused state.

Final response fields:
planner_draft_debug_status: passed | failed
root_cause: one concise sentence, or "none" if passed
"""
        timeout = int(os.environ.get("PLANNER_DRAFT_DEBUG_TIMEOUT_SECONDS", "180"))
        try:
            runner = AgentRunner(
                timeout_seconds=timeout,
                allowed_tools=build_allowed_tools(
                    ["Read"],
                    ["test_debug"],
                    mcp_config_dir=run_dir,
                ),
                log_tools=True,
                on_tool_use=getattr(self, "on_tool_use", None),
                on_progress=getattr(self, "on_progress", None),
                on_task_enqueued=getattr(self, "on_task_enqueued", None),
                cwd=run_dir,
                owner_type=getattr(self, "owner_type", None),
                owner_id=getattr(self, "owner_id", None),
                owner_label=getattr(self, "owner_label", None),
                requires_live_browser=True,
                model_tier=getattr(self, "model_tier", None),
                env_vars=getattr(self, "test_data_env_vars", {}),
                inject_memory=False,
                capture_memory=False,
                force_direct_execution=True,
                preserve_browser_on_failure=True,
                autopilot_retry_enabled=bool(getattr(self, "autopilot_retry_enabled", False)),
                autopilot_session_id=getattr(self, "autopilot_session_id", None),
                autopilot_stable_key=getattr(self, "autopilot_stable_key", None),
                autopilot_agent_kind=getattr(self, "autopilot_agent_kind", "test_generation_debug"),
                autopilot_source_type=getattr(self, "autopilot_source_type", None),
                autopilot_source_id=getattr(self, "autopilot_source_id", None),
                autopilot_checklist_title=getattr(self, "autopilot_checklist_title", None),
                autopilot_phase_name=getattr(self, "autopilot_phase_name", None),
                autopilot_checklist_kind=getattr(self, "autopilot_checklist_kind", None),
            )
            result = await runner.run(prompt)
            output = result.output or ""
            tool_call_names = [call.name for call in result.tool_calls]
            output_lower = output.lower()
            debug_tool_unavailable = (
                result.success
                and not tool_call_names
                and "test_debug" in output_lower
                and (
                    "not available" in output_lower
                    or "unavailable" in output_lower
                    or "no `test_debug`" in output_lower
                )
            )
            static_valid = False
            if debug_tool_unavailable:
                try:
                    draft_content = draft_path.read_text()
                    static_valid = (
                        "@playwright/test" in draft_content
                        and "test(" in draft_content
                        and ("expect(" in draft_content or "test.fixme" in draft_content)
                        and "```" not in draft_content
                    )
                except OSError:
                    static_valid = False
            status = "passed" if static_valid or (result.success and "failed" not in output_lower) else "failed"
            return {
                "attempted": True,
                "status": status,
                "path": str(draft_path),
                "browser": browser,
                "timed_out": result.timed_out,
                "success": result.success,
                "tool_calls": tool_call_names,
                "output_preview": truncate_middle(output, head=1000, tail=1000),
                **({"fallback_validation": "static"} if static_valid else {}),
                **({"error": result.error} if result.error else {}),
            }
        except Exception as exc:
            logger.warning("Planner draft test_debug validation failed: %s", exc)
            return {
                "attempted": True,
                "status": "error",
                "path": str(draft_path),
                "browser": browser,
                "error": str(exc),
            }

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
        handoff_manifest_path = init_manifest(run_dir, pipeline_type="browser")
        record_stage(
            handoff_manifest_path,
            "pipeline",
            status="running",
            metadata={
                "browser": browser,
                "skip_planning": skip_planning,
                "existing_test_path": existing_test_path,
                "force_api": force_api,
            },
        )
        self._configure_run_agent_env(run_dir)
        spec_file = Path(spec_path)
        spec_content = spec_file.read_text()
        auth_context = browser_auth_context or self._load_browser_auth_context()
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
            self._write_run_metrics(
                run_dir,
                credential_resolution_status="missing",
                failure_category="test_data",
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
        self._write_run_metrics(
            run_dir,
            credential_resolution_status="resolved" if (test_data_context or {}).get("refs") else "not_required",
        )

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
        record_artifact(
            handoff_manifest_path,
            "source_spec",
            run_dir / "spec.md",
            kind="markdown_spec",
            producer_stage="pipeline",
            required=True,
            consumers=["planner", "generator", "api_generator"],
            validation_status="valid",
        )
        record_artifact(
            handoff_manifest_path,
            "resolved_spec",
            run_dir / "spec_resolved.md",
            kind="markdown_spec",
            producer_stage="pipeline",
            required=True,
            consumers=["planner", "generator", "api_generator"],
            validation_status="valid",
        )

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
                handoff_manifest_path=handoff_manifest_path,
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
                        plan_path=None,
                        handoff_manifest_path=handoff_manifest_path,
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
            planner_draft_script_path: Path | None = None
            if not skip_planning:
                logger.info("Stage 1: Native Planning (browser exploration)...")
                report_progress("planning", "Exploring application structure...")
                record_stage(
                    handoff_manifest_path,
                    "planner",
                    status="running",
                    metadata={"target_url": target_url, "login_url": login_url},
                )
                record_consumption(
                    handoff_manifest_path,
                    "planner",
                    "resolved_spec",
                    status="used",
                    metadata={"path": str(run_dir / "spec_resolved.md")},
                )

                # Use resolved spec for planning so planner sees included templates
                resolved_spec_path = run_dir / "spec_resolved.md"
                try:
                    plan_path = await self._run_native_planner(
                        spec_path=str(resolved_spec_path),
                        run_dir=run_dir,
                        target_url=target_url,
                        login_url=login_url,
                        credentials=credentials,
                        auth_context=auth_context,
                    )
                except SpecGenerationError as exc:
                    error_msg = str(exc)
                    failure_category = (
                        exc.diagnostics.get("failure_category")
                        if isinstance(exc.diagnostics, dict)
                        else None
                    ) or "planner_validation"
                    logger.error("Native planner failed validation: %s", error_msg)
                    planner_result = getattr(self.native_planner, "last_agent_result", None)
                    record_attempt(
                        handoff_manifest_path,
                        "planner",
                        stage_attempt=1,
                        status="failed",
                        agent_session_id=getattr(planner_result, "session_id", None),
                        executor_mode="queue_or_direct",
                        model_tier=getattr(self.native_planner, "model_tier", None),
                        timeout_seconds=int(os.environ.get("PLANNER_TIMEOUT_SECONDS", os.environ.get("AGENT_TIMEOUT_SECONDS", "1800"))),
                        error_type=getattr(planner_result, "error_type", None) or failure_category,
                        tool_call_summary={
                            "count": len(getattr(planner_result, "tool_calls", []) or []),
                            "tools": [
                                getattr(call, "name", None)
                                for call in (getattr(planner_result, "tool_calls", []) or [])
                            ],
                        },
                        metadata={"diagnostics": exc.diagnostics},
                    )
                    (run_dir / "status.txt").write_text("error")
                    self._write_pipeline_error(
                        run_dir,
                        error_msg,
                        "runtime_failed" if failure_category == "runtime_failed" else "planning",
                        {"planner_diagnostics": exc.diagnostics},
                    )
                    record_stage(
                        handoff_manifest_path,
                        "planner",
                        status="failed",
                        failure_reason=error_msg,
                        metadata={"diagnostics": exc.diagnostics},
                    )
                    self._write_run_metrics(
                        run_dir,
                        planner_success=False,
                        failure_category=failure_category,
                    )
                    self._publish_agentic_summary(run_dir)
                    cleanup_orphaned_browsers()
                    return {
                        "success": False,
                        "error": error_msg,
                        "stage": "runtime_failed"
                        if failure_category == "runtime_failed"
                        else "planning",
                        "planner_diagnostics": exc.diagnostics,
                    }

                if plan_path and plan_path.exists():
                    logger.info(f"Plan created: {plan_path}")
                    try:
                        plan_text = plan_path.read_text()
                    except OSError:
                        plan_text = ""
                    run_plan_md_path = run_dir / "plan.md"
                    if plan_text:
                        run_plan_md_path.write_text(plan_text)
                    record_artifact(
                        handoff_manifest_path,
                        "planner_plan",
                        run_plan_md_path if run_plan_md_path.exists() else plan_path,
                        kind="planner_markdown_plan",
                        producer_stage="planner",
                        required=True,
                        consumers=["generator", "healer"],
                        validation_status="valid",
                        metadata={"source_path": str(plan_path)},
                    )
                    raw_draft_path = getattr(
                        self.native_planner, "last_draft_script_path", None
                    )
                    if raw_draft_path:
                        candidate_draft_path = Path(raw_draft_path)
                        if candidate_draft_path.exists():
                            planner_draft_script_path = candidate_draft_path
                            logger.info(
                                "Planner draft script created: %s",
                                planner_draft_script_path,
                            )
                            draft_debug = await self._debug_validate_planner_draft_script(
                                draft_path=planner_draft_script_path,
                                run_dir=run_dir,
                                browser=browser,
                            )
                            record_artifact(
                                handoff_manifest_path,
                                "planner_draft_script",
                                planner_draft_script_path,
                                kind="planner_draft_playwright",
                                producer_stage="planner",
                                required=True,
                                consumers=["generator", "healer"],
                                validation_status=(
                                    "valid"
                                    if draft_debug.get("status") == "passed"
                                    else "debug_failed"
                                ),
                                metadata={"debug_validation": draft_debug},
                            )
                    planner_selectors = []
                    planner_selectors = extract_plan_selectors(plan_text, limit=30) if plan_text else []
                    evidence_summary_path = run_dir / "planner_evidence_summary.json"
                    evidence_summary_path.write_text(
                        json.dumps(
                            {
                                "plan_path": str(run_plan_md_path if run_plan_md_path.exists() else plan_path),
                                "source_plan_path": str(plan_path),
                                "planner_draft_script_path": str(planner_draft_script_path)
                                if planner_draft_script_path
                                else None,
                                "selector_count": len(planner_selectors),
                                "selectors": planner_selectors,
                            },
                            indent=2,
                        )
                    )
                    record_artifact(
                        handoff_manifest_path,
                        "planner_evidence_summary",
                        evidence_summary_path,
                        kind="planner_evidence_summary",
                        producer_stage="planner",
                        required=False,
                        consumers=["generator", "healer", "reporting"],
                        validation_status="valid",
                    )
                    planner_result = getattr(self.native_planner, "last_agent_result", None)
                    record_attempt(
                        handoff_manifest_path,
                        "planner",
                        stage_attempt=1,
                        status="passed",
                        agent_session_id=getattr(planner_result, "session_id", None),
                        executor_mode="queue_or_direct",
                        model_tier=getattr(self.native_planner, "model_tier", None),
                        timeout_seconds=int(os.environ.get("PLANNER_TIMEOUT_SECONDS", os.environ.get("AGENT_TIMEOUT_SECONDS", "1800"))),
                        error_type=getattr(planner_result, "error_type", None),
                        tool_call_summary={
                            "count": len(getattr(planner_result, "tool_calls", []) or []),
                            "tools": [
                                getattr(call, "name", None)
                                for call in (getattr(planner_result, "tool_calls", []) or [])
                            ],
                        },
                        input_artifact_hashes=self._manifest_artifact_hashes(
                            handoff_manifest_path,
                            ["resolved_spec"],
                        ),
                        output_artifact_hash=self._file_sha256(
                            run_plan_md_path if run_plan_md_path.exists() else plan_path
                        ),
                        metadata={
                            "planner_draft_script_path": str(planner_draft_script_path)
                            if planner_draft_script_path
                            else None,
                        },
                    )
                    record_stage(
                        handoff_manifest_path,
                        "planner",
                        status="ready",
                        metadata={
                            "plan_path": str(run_plan_md_path if run_plan_md_path.exists() else plan_path),
                            "source_plan_path": str(plan_path),
                            "planner_draft_script_path": str(planner_draft_script_path)
                            if planner_draft_script_path
                            else None,
                            "selector_count": len(planner_selectors),
                        },
                    )
                    self._emit_handoff_event(
                        "planner_handoff_ready",
                        "Planner handoff artifacts are ready.",
                        payload={
                            "artifacts": self._manifest_artifact_payload(
                                handoff_manifest_path,
                                [
                                    "planner_plan",
                                    "planner_draft_script",
                                    "planner_evidence_summary",
                                ],
                            ),
                            "selector_count": len(planner_selectors),
                        },
                    )
                    self._write_run_metrics(run_dir, planner_success=True)
                else:
                    logger.warning(
                        "Planner didn't create a structured plan, continuing with original spec"
                    )
                    record_stage(
                        handoff_manifest_path,
                        "planner",
                        status="skipped_or_missing",
                        failure_reason="planner did not create a structured plan",
                    )
                    self._write_run_metrics(run_dir, planner_success=False)
            else:
                record_stage(
                    handoff_manifest_path,
                    "planner",
                    status="skipped",
                    metadata={"reason": "skip_planning"},
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
            if not plan_path:
                record_artifact(
                    handoff_manifest_path,
                    "planner_plan",
                    run_dir / "plan.md",
                    kind="planner_markdown_plan",
                    producer_stage="planner",
                    required=False,
                    consumers=["generator", "healer"],
                    validation_status="optional_missing",
                    failure_reason="planning was skipped or did not produce a plan",
                )
            if not planner_draft_script_path:
                record_artifact(
                    handoff_manifest_path,
                    "planner_draft_script",
                    run_dir / "plan.draft.spec.ts",
                    kind="planner_draft_playwright",
                    producer_stage="planner",
                    required=False,
                    consumers=["generator", "healer"],
                    validation_status="optional_missing",
                    failure_reason="planning was skipped or did not produce a draft script",
                )
            record_stage(
                handoff_manifest_path,
                "generator",
                status="running",
                metadata={
                    "target_url": target_url,
                    "plan_path": str(plan_path) if plan_path else None,
                    "planner_draft_script_path": str(planner_draft_script_path)
                    if planner_draft_script_path
                    else None,
                },
            )

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
                run_dir=run_dir,
                browser=browser,
                design_context=design_context,
                memory_run_id=getattr(self, "_memory_run_id", None),
                auth_context=auth_context,
                execution_credentials=credentials,
                plan_path=plan_path,
                planner_draft_script_path=planner_draft_script_path,
                handoff_manifest_path=handoff_manifest_path,
            )

            if not test_path or not test_path.exists():
                diagnostics = self._generator_failure_diagnostics()
                error_msg = (
                    diagnostics.get("last_agent_result", {}).get("error")
                    or diagnostics.get("exception")
                    or "Native generator failed to create test file"
                )
                generator_result = getattr(self.native_generator, "last_agent_result", None)
                record_attempt(
                    handoff_manifest_path,
                    "generator",
                    stage_attempt=1,
                    status="failed",
                    agent_session_id=getattr(generator_result, "session_id", None),
                    executor_mode="queue_or_direct",
                    model_tier=getattr(self.native_generator, "model_tier", None),
                    timeout_seconds=int(os.environ.get("GENERATOR_TIMEOUT_SECONDS", os.environ.get("AGENT_TIMEOUT_SECONDS", "1800"))),
                    error_type=getattr(generator_result, "error_type", None) or "no_generated_test",
                    tool_call_summary={
                        "count": len(getattr(generator_result, "tool_calls", []) or []),
                        "tools": [
                            getattr(call, "name", None)
                            for call in (getattr(generator_result, "tool_calls", []) or [])
                        ],
                    },
                    input_artifact_hashes=self._manifest_artifact_hashes(
                        handoff_manifest_path,
                        ["planner_plan", "planner_draft_script"],
                    ),
                    metadata=diagnostics,
                )
                (run_dir / "status.txt").write_text("error")
                self._write_pipeline_error(run_dir, error_msg, "generation", diagnostics)
                record_stage(
                    handoff_manifest_path,
                    "generator",
                    status="failed",
                    failure_reason=error_msg,
                    metadata={
                        **getattr(self.native_generator, "last_handoff_consumption", {}),
                        **diagnostics,
                    },
                )
                self._write_run_metrics(run_dir, generation_success=False)
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

            generation_repair_metadata: dict[str, Any] = {}
            validation_error = self._validate_generated_test_file(
                test_path=test_path,
                run_dir=run_dir,
                browser=browser,
                test_type="browser",
            )
            generated_test_metadata = dict(
                getattr(self.native_generator, "last_handoff_consumption", {}) or {}
            )
            generator_self_run = (
                getattr(self.native_generator, "last_self_run_result", None) or {}
            )
            if generator_self_run:
                generated_test_metadata["generator_self_run_status"] = (
                    generator_self_run.get("final_status")
                )
                generated_test_metadata["generator_self_heal_attempts"] = getattr(
                    self.native_generator, "last_self_heal_attempts", 0
                )
                if getattr(self.native_generator, "last_self_heal_artifact_path", None):
                    generated_test_metadata["generator_self_heal_artifact"] = str(
                        self.native_generator.last_self_heal_artifact_path
                    )
            record_artifact(
                handoff_manifest_path,
                "generated_test",
                test_path,
                kind="playwright_test",
                producer_stage="generator",
                required=True,
                consumers=["test_run", "healer", "reporting"],
                validation_status="pending_validation",
                metadata=generated_test_metadata,
            )
            generator_result = getattr(self.native_generator, "last_agent_result", None)
            record_attempt(
                handoff_manifest_path,
                "generator",
                stage_attempt=1,
                status="passed",
                agent_session_id=getattr(generator_result, "session_id", None),
                executor_mode="queue_or_direct",
                model_tier=getattr(self.native_generator, "model_tier", None),
                timeout_seconds=int(os.environ.get("GENERATOR_TIMEOUT_SECONDS", os.environ.get("AGENT_TIMEOUT_SECONDS", "1800"))),
                error_type=getattr(generator_result, "error_type", None),
                tool_call_summary={
                    "count": len(getattr(generator_result, "tool_calls", []) or []),
                    "tools": [
                        getattr(call, "name", None)
                        for call in (getattr(generator_result, "tool_calls", []) or [])
                    ],
                },
                input_artifact_hashes=self._manifest_artifact_hashes(
                    handoff_manifest_path,
                    ["planner_plan", "planner_draft_script"],
                ),
                output_artifact_hash=self._file_sha256(test_path),
                metadata=generated_test_metadata,
            )
            validation_status = validate_artifact(
                handoff_manifest_path,
                "generated_test",
                validator=lambda _path: (validation_error is None, validation_error),
            )
            if validation_error:
                generation_repair_metadata = await self._attempt_generation_format_repair(
                    test_path=test_path,
                    run_dir=run_dir,
                    browser=browser,
                    test_type="browser",
                    original_validation_error=validation_error,
                    spec_content=resolved_spec_content,
                    spec_path=resolved_spec_path,
                    target_url=target_url,
                    plan_path=plan_path,
                    planner_draft_script_path=planner_draft_script_path,
                )
                repair_artifact_path = generation_repair_metadata.get(
                    "generation_repair_artifact_path"
                )
                if repair_artifact_path:
                    record_artifact(
                        handoff_manifest_path,
                        "generation_repair_attempt",
                        Path(str(repair_artifact_path)),
                        kind="generation_repair_attempt",
                        producer_stage="generator",
                        required=False,
                        consumers=["reporting"],
                        validation_status="valid",
                        metadata=generation_repair_metadata,
                    )
                if generation_repair_metadata.get("generation_repair_accepted"):
                    record_artifact(
                        handoff_manifest_path,
                        "generated_test",
                        test_path,
                        kind="playwright_test",
                        producer_stage="generator",
                        required=True,
                        consumers=["test_run", "healer", "reporting"],
                        validation_status="pending_validation",
                        metadata={
                            **getattr(self.native_generator, "last_handoff_consumption", {}),
                            **generation_repair_metadata,
                        },
                    )
                    validation_error = self._validate_generated_test_file(
                        test_path=test_path,
                        run_dir=run_dir,
                        browser=browser,
                        test_type="browser",
                    )
                    validation_status = validate_artifact(
                        handoff_manifest_path,
                        "generated_test",
                        validator=lambda _path: (validation_error is None, validation_error),
                    )

            if validation_error:
                logger.error(validation_error)
                (run_dir / "status.txt").write_text("error")
                self._write_pipeline_error(
                    run_dir,
                    validation_error,
                    "generation_validation",
                    generation_repair_metadata,
                )
                self._write_run_metrics(
                    run_dir,
                    generation_success=False,
                    failure_category="generation_validation",
                    **generation_repair_metadata,
                )
                record_stage(
                    handoff_manifest_path,
                    "generator",
                    status="failed",
                    failure_reason=validation_error,
                    metadata={
                        **getattr(self.native_generator, "last_handoff_consumption", {}),
                        "validation": validation_status,
                    **generation_repair_metadata,
                },
            )
                self._publish_agentic_summary(run_dir)
                return {
                    "success": False,
                    "error": validation_error,
                    "stage": "generation_validation",
                    **generation_repair_metadata,
                }

            logger.info(f"Test generated: {test_path}")
            record_stage(
                handoff_manifest_path,
                "generator",
                status="ready",
                metadata={
                    **getattr(self.native_generator, "last_handoff_consumption", {}),
                    "test_path": str(test_path),
                    "validation": validation_status,
                    **generation_repair_metadata,
                },
            )
            self._emit_handoff_event(
                "generator_handoff_consumed",
                "Generator consumed planner handoff context.",
                payload={
                    "artifacts": self._manifest_artifact_payload(
                        handoff_manifest_path,
                        ["planner_plan", "planner_draft_script", "generated_test"],
                    ),
                    "consumption": getattr(self.native_generator, "last_handoff_consumption", {}),
                    "validation": validation_status,
                    "repair": generation_repair_metadata,
                },
            )
            self._write_run_metrics(
                run_dir,
                generation_success=True,
                generator_self_run_status=(
                    getattr(self.native_generator, "last_self_run_result", {}) or {}
                ).get("final_status"),
                generator_self_heal_attempts=getattr(
                    self.native_generator, "last_self_heal_attempts", 0
                ),
                **generation_repair_metadata,
            )
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

            generator_self_run = (
                getattr(self.native_generator, "last_self_run_result", None) or {}
            )
            if getattr(self.native_generator, "last_self_heal_passed", False):
                logger.info("Skipping initial pipeline test run; generator self-run already passed.")
                record_stage(
                    handoff_manifest_path,
                    "test_run",
                    status="passed",
                    metadata={
                        "exit_code": 0,
                        "source": "generator_self_run",
                        "generator_self_run_status": generator_self_run.get("final_status"),
                        "generator_self_heal_attempts": getattr(
                            self.native_generator, "last_self_heal_attempts", 0
                        ),
                    },
                )
                self._write_run_metrics(
                    run_dir,
                    initial_run_passed=True,
                    healing_started=False,
                    healing_attempts=0,
                    heal_rescued=False,
                    generator_self_run_status=generator_self_run.get("final_status"),
                    generator_self_heal_attempts=getattr(
                        self.native_generator, "last_self_heal_attempts", 0
                    ),
                )
                stability_result = await self._verify_stability_or_harden(
                    test_path=test_path,
                    run_dir=run_dir,
                    browser=browser,
                    success_stage="completed",
                    attempts=getattr(self.native_generator, "last_self_heal_attempts", 0),
                )
                if stability_result:
                    self._write_run_metrics(run_dir, stable_first_pass=False)
                    return stability_result
                self._record_passing_selectors(test_path)
                (run_dir / "status.txt").write_text("passed")
                self._write_run_metrics(run_dir, stable_first_pass=True)
                self._publish_agentic_summary(run_dir)
                return {
                    "success": True,
                    "test_path": str(test_path),
                    "attempts": getattr(self.native_generator, "last_self_heal_attempts", 0),
                    "stage": "completed",
                    "generator_self_run": generator_self_run,
                }

            # Stage 3: Run test
            logger.info("Stage 3: Running test...")
            report_progress("testing", "Running generated test...")
            record_stage(
                handoff_manifest_path,
                "test_run",
                status="running",
                metadata={"browser": browser, "test_path": str(test_path)},
            )
            record_consumption(
                handoff_manifest_path,
                "test_run",
                "generated_test",
                status="used",
                metadata={"path": str(test_path)},
            )

            result = self._run_test(str(test_path), str(run_dir), browser)

            if result.passed:
                logger.info("Test PASSED on first run!")
                record_stage(
                    handoff_manifest_path,
                    "test_run",
                    status="passed",
                    metadata={"exit_code": result.exit_code},
                )
                self._write_run_metrics(
                    run_dir,
                    initial_run_passed=True,
                    healing_started=False,
                    healing_attempts=0,
                    heal_rescued=False,
                )
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
                    self._write_run_metrics(run_dir, stable_first_pass=False)
                    return stability_result
                self._record_passing_selectors(test_path)
                (run_dir / "status.txt").write_text("passed")
                self._write_run_metrics(run_dir, stable_first_pass=True)
                self._publish_agentic_summary(run_dir)
                return {
                    "success": True,
                    "test_path": str(test_path),
                    "attempts": 0,
                    "stage": "completed",
                }

            logger.error(f"Test FAILED: {result.error_summary}")
            failure_category = categorize_error(result.error_summary or result.output[-2000:])
            record_stage(
                handoff_manifest_path,
                "test_run",
                status="failed",
                failure_reason=result.error_summary or result.output[-500:],
                metadata={
                    "exit_code": result.exit_code,
                    "failure_category": failure_category,
                },
            )
            self._emit_handoff_event(
                "test_run_handoff_failed",
                "Generated test failed and is ready for healer handoff.",
                level="warning",
                payload={
                    "artifacts": self._manifest_artifact_payload(
                        handoff_manifest_path,
                        ["generated_test", "planner_plan", "planner_draft_script"],
                    ),
                    "failure_category": failure_category,
                    "error_summary": result.error_summary,
                },
            )
            self._write_run_metrics(
                run_dir,
                initial_run_passed=False,
                stable_first_pass=False,
                failure_category=failure_category,
            )
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
                    plan_path=plan_path,
                    handoff_manifest_path=handoff_manifest_path,
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
                    "handoffManifestPath": str(run_dir / "handoff_manifest.json"),
                    "plannerDraftScriptPath": (
                        str(getattr(self.native_planner, "last_draft_script_path", ""))
                        if getattr(self.native_planner, "last_draft_script_path", None)
                        else None
                    ),
                    "steps": [],  # Will be populated from the generated plan
                }
                (run_dir / "plan.json").write_text(json.dumps(plan_data, indent=2))

            return plan_path

        except SpecGenerationError:
            raise
        except Exception as e:
            logger.warning(f"Native planner error: {e}")
            return None

    async def _run_native_generator(
        self,
        spec_path: str,
        target_url: str,
        output_name: str | None = None,
        run_dir: Path | None = None,
        browser: str | None = None,
        design_context: str | None = None,
        memory_run_id: str | None = None,
        auth_context: dict[str, Any] | None = None,
        execution_credentials: dict[str, str] | None = None,
        plan_path: Path | None = None,
        planner_draft_script_path: Path | None = None,
        handoff_manifest_path: Path | None = None,
    ) -> Path | None:
        """Run native generator to create test code.

        Args:
            spec_path: Path to the spec file (can be resolved spec with includes expanded)
            target_url: URL of the application to test
            output_name: Override for output test file name (without extension)
        """
        try:
            self._last_native_generator_exception = None
            if handoff_manifest_path:
                if plan_path:
                    record_consumption(
                        handoff_manifest_path,
                        "generator",
                        "planner_plan",
                        status="used" if plan_path.exists() else "missing",
                        reason=None if plan_path.exists() else "plan path does not exist",
                        metadata={"path": str(plan_path)},
                    )
                if planner_draft_script_path:
                    record_consumption(
                        handoff_manifest_path,
                        "generator",
                        "planner_draft_script",
                        status="used" if planner_draft_script_path.exists() else "missing",
                        reason=None
                        if planner_draft_script_path.exists()
                        else "draft script path does not exist",
                        metadata={"path": str(planner_draft_script_path)},
                    )
            test_path = await self.native_generator.generate_test(
                spec_path=spec_path,
                target_url=target_url,
                output_name=output_name,
                self_run_browser=browser,
                self_run_output_dir=run_dir,
                design_context=design_context,
                memory_run_id=memory_run_id,
                auth_context=auth_context,
                execution_credentials=execution_credentials,
                plan_path=plan_path,
                planner_draft_script_path=planner_draft_script_path,
                handoff_manifest_path=handoff_manifest_path,
            )
            return test_path
        except Exception as e:
            logger.error(f"Native generator error: {e}")
            self._last_native_generator_exception = str(e)
            return None

    def _generator_failure_diagnostics(self) -> dict[str, Any]:
        result = getattr(getattr(self, "native_generator", None), "last_agent_result", None)
        diagnostics: dict[str, Any] = {}
        if self._last_native_generator_exception:
            diagnostics["exception"] = self._last_native_generator_exception
        if result is not None:
            diagnostics["last_agent_result"] = {
                "error": getattr(result, "error", None),
                "error_type": getattr(result, "error_type", None),
                "api_error_status": getattr(result, "api_error_status", None),
                "messages_received": getattr(result, "messages_received", 0),
                "text_blocks_received": getattr(result, "text_blocks_received", 0),
                "tool_calls": len(getattr(result, "tool_calls", []) or []),
                "last_tool": (
                    getattr((getattr(result, "tool_calls", []) or [])[-1], "name", None)
                    if getattr(result, "tool_calls", None)
                    else None
                ),
                "session_id": getattr(result, "session_id", None),
                "stop_reason": getattr(result, "stop_reason", None),
            }
        return diagnostics

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

    def _write_run_metrics(self, run_dir: Path, **updates: Any) -> dict[str, Any]:
        """Merge canonical first-pass/healing metrics into run_metrics.json."""
        path = run_dir / "run_metrics.json"
        metrics: dict[str, Any] = {}
        try:
            if path.exists():
                loaded = json.loads(path.read_text())
                if isinstance(loaded, dict):
                    metrics.update(loaded)
        except Exception as exc:
            logger.debug(f"Could not read run_metrics.json: {exc}")

        metrics.setdefault("schema_version", "1.0")
        metrics.setdefault("initial_run_passed", None)
        metrics.setdefault("stable_first_pass", None)
        metrics.setdefault("healing_started", False)
        metrics.setdefault("healing_attempts", 0)
        metrics.setdefault("heal_rescued", False)
        metrics.setdefault("generation_success", None)
        metrics.setdefault("planner_success", None)
        metrics.setdefault("credential_resolution_status", "unknown")
        metrics.setdefault("failure_category", None)
        metrics.setdefault("cost_usd", None)
        metrics.setdefault("wall_time_seconds", None)
        metrics.update({key: value for key, value in updates.items() if value is not None})
        metrics["updated_at"] = datetime.now().isoformat()

        try:
            path.write_text(json.dumps(metrics, indent=2))
        except OSError as exc:
            logger.debug(f"Could not write run_metrics.json: {exc}")
        return metrics

    def _validate_generated_test_file(
        self,
        *,
        test_path: Path,
        run_dir: Path,
        browser: str,
        test_type: str,
    ) -> str | None:
        """Deterministically reject malformed generated Playwright files before execution."""
        try:
            content = test_path.read_text()
        except OSError as exc:
            return f"Generated test file could not be read: {exc}"

        stripped = content.strip()
        if len(stripped) < 100:
            return f"Generated test file is too small ({len(stripped)} chars) - likely incomplete generation"
        if "```" in stripped:
            return "Generated test file contains markdown fences or narrative output"
        if not self._has_supported_playwright_test_import(stripped):
            return "Generated test file is missing @playwright/test import or project test-data fixture import"
        if "test(" not in stripped and "test.describe" not in stripped:
            return "Generated test file is missing test() or test.describe()"
        if "expect(" not in stripped and "test.fixme" not in stripped:
            return "Generated test file has no Playwright assertions or explicit test.fixme()"
        if test_type == "api" and " request " not in stripped and "{ request" not in stripped:
            return "Generated API test does not use the Playwright request fixture"

        if not getattr(self, "generated_preflight_list_enabled", False):
            return None

        try:
            cmd = (
                f"npx playwright test --list '{test_path}' --project {browser}"
                f"{playwright_config_cli_arg(str(run_dir))}"
            )
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
                env={
                    **{
                        key: value
                        for key, value in os.environ.copy().items()
                        if not key.startswith("TESTDATA_")
                    },
                    **getattr(self, "test_data_env_vars", {}),
                },
            )
            if result.returncode != 0:
                output = (result.stdout + result.stderr).strip()
                return f"Generated test failed Playwright list preflight: {output[:1000]}"
        except subprocess.TimeoutExpired:
            return "Generated test Playwright list preflight timed out"
        except Exception as exc:
            return f"Generated test Playwright list preflight failed: {exc}"
        return None

    @staticmethod
    def _has_supported_playwright_test_import(content: str) -> bool:
        if "@playwright/test" in content:
            return True

        for match in re.finditer(
            r"import\s*\{(?P<names>[^}]+)\}\s*from\s*['\"](?P<source>[^'\"]+)['\"]",
            content,
        ):
            names = match.group("names")
            source = match.group("source").replace("\\", "/")
            if (
                source.endswith("fixtures/test-data")
                and re.search(r"\btest\b", names)
                and re.search(r"\bexpect\b", names)
                and ("testData" in content or "QUORVEX_TEST_DATA_FILE" in content)
            ):
                return True
        return False

    @staticmethod
    def _should_attempt_generation_format_repair(validation_error: str | None) -> bool:
        if not validation_error:
            return False
        lowered = validation_error.lower()
        if "too small" in lowered or "could not be read" in lowered:
            return False
        repairable_markers = (
            "missing @playwright/test import",
            "missing @playwright/test import or project test-data fixture import",
            "markdown fences",
            "missing test()",
            "missing test.describe",
            "no playwright assertions",
            "request fixture",
        )
        return any(marker in lowered for marker in repairable_markers)

    @staticmethod
    def _full_content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()

    @staticmethod
    def _redact_sensitive_text(content: str) -> str:
        patterns = (
            r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+",
            r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization|credential)\b(\s*[:=]\s*)([^\s,;`]+)",
        )
        redacted = content or ""
        for pattern in patterns:
            redacted = re.sub(
                pattern,
                lambda match: f"{match.group(1)}{match.group(2) if len(match.groups()) > 1 else ' '}[REDACTED]",
                redacted,
            )
        return redacted

    @classmethod
    def _content_preview(cls, content: str, limit: int = 2000) -> str:
        normalized = cls._redact_sensitive_text(content).replace("\x00", " ").strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit] + f"\n...[truncated {len(normalized) - limit} chars]"

    def _write_generation_repair_artifact(self, run_dir: Path, metadata: dict[str, Any]) -> Path | None:
        try:
            artifact = {
                key: value
                for key, value in metadata.items()
                if not key.startswith("_")
            }
            path = run_dir / "generation_repair_attempt.json"
            path.write_text(json.dumps(artifact, indent=2))
            metadata["generation_repair_artifact_path"] = str(path)
            return path
        except OSError as exc:
            logger.debug("Could not write generation repair artifact: %s", exc)
            return None

    def _safe_fixture_context_summary(self) -> dict[str, Any]:
        context = getattr(self, "test_data_execution_context", {}) or {}
        return {
            "refs": list(context.get("refs") or []),
            "missing": list(context.get("missing") or []),
            "runtime_fixture_file": context.get("runtime_fixture_file"),
            "fixture_env_injected": bool(getattr(self, "test_data_env_vars", {}).get("QUORVEX_TEST_DATA_FILE")),
        }

    def _build_generation_repair_prompt(
        self,
        *,
        generated_code: str,
        original_validation_error: str,
        spec_content: str,
        spec_path: Path | str,
        target_url: str,
        plan_path: Path | None,
        planner_draft_script_path: Path | None,
        test_path: Path,
    ) -> str:
        plan_content = ""
        if plan_path and plan_path.exists():
            try:
                plan_content = plan_path.read_text()
            except OSError:
                plan_content = ""

        draft_content = ""
        if planner_draft_script_path and planner_draft_script_path.exists():
            try:
                draft_content = planner_draft_script_path.read_text()
            except OSError:
                draft_content = ""

        fixture_context = self._safe_fixture_context_summary()
        return f"""You are a bounded Playwright TypeScript formatter/repair agent.

Repair the generated test file so it passes deterministic structural validation.
Do not browse, inspect files, call tools, or change scenario intent.
Return TypeScript only: no markdown fences, no commentary, no prose.
Keep the same destination file path: {test_path}

Original validation error:
{original_validation_error}

Target URL:
{target_url}

Source spec ({spec_path}):
```markdown
{truncate_text_to_tokens(self._redact_sensitive_text(spec_content), context_budget_for_stage("generation_repair_spec", 1800))}
```

Fixture context:
```json
{json.dumps(fixture_context, indent=2, sort_keys=True)}
```

Planner plan:
```markdown
{truncate_text_to_tokens(self._redact_sensitive_text(plan_content), context_budget_for_stage("generation_repair_plan", 1400))}
```

Planner draft script:
```typescript
{truncate_text_to_tokens(self._redact_sensitive_text(draft_content), context_budget_for_stage("generation_repair_draft", 1400))}
```

Current generated file:
```typescript
{truncate_text_to_tokens(self._redact_sensitive_text(generated_code), context_budget_for_stage("generation_repair_code", 2600))}
```

Requirements:
- Import `test` and `expect` from `@playwright/test`, unless the code uses project test data.
- If the code uses project test data, import `test` and `expect` from the existing fixture helper path already present in the file or from `../fixtures/test-data`.
- Use `testData.get(...)` or `testData.field(...)` for project test data. Never write `process.env.TESTDATA_*`.
- Include at least one `test(...)` or `test.describe(...)`.
- Include Playwright assertions with `expect(...)` unless the test is explicitly `test.fixme(...)`.
- Preserve the user-visible flow and selectors from the current generated file, planner plan, and draft script.
"""

    async def _query_generation_repair_agent(self, prompt: str):
        timeout = int(os.environ.get("GENERATION_REPAIR_TIMEOUT_SECONDS", "180"))
        raw_budget = os.environ.get("GENERATION_REPAIR_TOKEN_BUDGET", "12000")
        try:
            token_budget = max(1000, int(raw_budget))
        except ValueError:
            token_budget = 12000
        runner = AgentRunner(
            timeout_seconds=timeout,
            allowed_tools=[],
            tools=[],
            log_tools=False,
            cwd=getattr(getattr(self, "native_generator", None), "cwd", None),
            owner_type=self.owner_type,
            owner_id=self.owner_id,
            owner_label=self.owner_label,
            requires_live_browser=False,
            model_tier=self.model_tier,
            task_budget={"total": token_budget},
            inject_memory=False,
            capture_memory=False,
            env_vars=getattr(self, "test_data_env_vars", {}),
            autopilot_retry_enabled=bool(getattr(self, "autopilot_retry_enabled", False)),
            autopilot_session_id=getattr(self, "autopilot_session_id", None),
            autopilot_stable_key=getattr(self, "autopilot_stable_key", None),
            autopilot_agent_kind=getattr(self, "autopilot_agent_kind", "test_generation_repair"),
            autopilot_source_type=getattr(self, "autopilot_source_type", None),
            autopilot_source_id=getattr(self, "autopilot_source_id", None),
            autopilot_checklist_title=getattr(self, "autopilot_checklist_title", None),
            autopilot_phase_name=getattr(self, "autopilot_phase_name", None),
            autopilot_checklist_kind=getattr(self, "autopilot_checklist_kind", None),
        )
        return await runner.run(prompt)

    async def _attempt_generation_format_repair(
        self,
        *,
        test_path: Path,
        run_dir: Path,
        browser: str,
        test_type: str,
        original_validation_error: str,
        spec_content: str,
        spec_path: Path | str,
        target_url: str,
        plan_path: Path | None,
        planner_draft_script_path: Path | None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "generation_repair_attempted": False,
            "generation_repair_accepted": False,
            "original_validation_error": original_validation_error,
        }
        try:
            current_code = test_path.read_text()
        except OSError as exc:
            metadata["generation_repair_error"] = f"could not read generated file: {exc}"
            self._write_generation_repair_artifact(run_dir, metadata)
            return metadata

        metadata.update(
            {
                "generated_file_hash_before_repair": self._full_content_hash(current_code),
                "generated_file_preview_before_repair": self._content_preview(current_code),
            }
        )

        if not self._should_attempt_generation_format_repair(original_validation_error):
            metadata["generation_repair_skipped_reason"] = "validation_error_not_repairable_by_format_repair"
            self._write_generation_repair_artifact(run_dir, metadata)
            return metadata

        metadata["generation_repair_attempted"] = True
        prompt = self._build_generation_repair_prompt(
            generated_code=current_code,
            original_validation_error=original_validation_error,
            spec_content=spec_content,
            spec_path=spec_path,
            target_url=target_url,
            plan_path=plan_path,
            planner_draft_script_path=planner_draft_script_path,
            test_path=test_path,
        )

        try:
            repair_result = await self._query_generation_repair_agent(prompt)
        except Exception as exc:
            metadata["generation_repair_error"] = str(exc)
            self._write_generation_repair_artifact(run_dir, metadata)
            return metadata

        repaired_output = str(getattr(repair_result, "output", "") or "")
        repaired_code = object.__new__(NativeGenerator)._extract_code(repaired_output)
        if repaired_code is None:
            candidate = repaired_output.strip()
            metadata["generation_repair_validation_error"] = (
                "repair output did not contain a valid Playwright TypeScript test"
            )
            metadata["repaired_output"] = {
                "length": len(candidate),
                "hash": self._full_content_hash(candidate) if candidate else None,
                "preview": self._content_preview(candidate),
            }
            self._write_generation_repair_artifact(run_dir, metadata)
            return metadata

        test_path.write_text(repaired_code.rstrip() + "\n")
        repair_validation_error = self._validate_generated_test_file(
            test_path=test_path,
            run_dir=run_dir,
            browser=browser,
            test_type=test_type,
        )
        repaired_hash = self._full_content_hash(test_path.read_text())
        metadata["repaired_file_hash"] = repaired_hash
        metadata["generation_repaired_file_hash"] = repaired_hash
        metadata["repaired_output"] = {
            "length": len(repaired_code),
            "hash": repaired_hash,
            "preview": self._content_preview(repaired_code),
        }
        if repair_validation_error:
            metadata["generation_repair_validation_error"] = repair_validation_error
            test_path.write_text(current_code)
            metadata["generation_repair_reverted"] = True
            self._write_generation_repair_artifact(run_dir, metadata)
            return metadata

        metadata["generation_repair_accepted"] = True
        artifact_path = self._write_generation_repair_artifact(run_dir, metadata)
        metadata["generation_repair_artifact_path"] = str(artifact_path) if artifact_path else None
        return metadata

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
            self._write_run_metrics(
                run_dir,
                stable_first_pass=False,
                healing_started=True,
                healing_attempts=attempts + 1,
                heal_rescued=False,
            )
            stability_result["attempts"] = attempts
            return stability_result

        rerun = self._run_test(str(test_path), str(run_dir), browser)
        if not rerun.passed:
            logger.warning("Flake-hardening changes did not pass the immediate rerun")
            self._write_run_metrics(
                run_dir,
                stable_first_pass=False,
                healing_started=True,
                healing_attempts=attempts + 1,
                heal_rescued=False,
            )
            stability_result["attempts"] = attempts + 1
            return stability_result

        second_stability_result = self._run_stability_gate(
            test_path=test_path, run_dir=run_dir, browser=browser
        )
        if second_stability_result:
            self._write_run_metrics(
                run_dir,
                stable_first_pass=False,
                healing_started=True,
                healing_attempts=attempts + 1,
                heal_rescued=False,
            )
            second_stability_result["attempts"] = attempts + 1
            return second_stability_result

        (run_dir / "status.txt").write_text("passed")
        self._write_run_metrics(
            run_dir,
            stable_first_pass=False,
            healing_started=True,
            healing_attempts=attempts + 1,
            heal_rescued=True,
        )
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
    def _file_sha256(path: Path | str | None) -> str | None:
        if not path:
            return None
        file_path = Path(path)
        if not file_path.exists() or not file_path.is_file():
            return None
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

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
    def _has_test_fixme(content: str) -> bool:
        return bool(re.search(r"\btest\.fixme\s*\(", content or ""))

    @classmethod
    def _is_assertion_removal_allowed(cls, content: str) -> bool:
        return cls._has_test_fixme(content)

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
        failure_metadata: dict[str, Any] | None = None,
        triage_allows_fixme: bool = False,
    ) -> dict[str, Any]:
        tools = [str(call.get("tool") or self._normalized_tool_name(call.get("name"))) for call in tool_calls]
        tool_set = set(tools)
        changed = content_before != content_after
        missing: list[str] = []
        category = self._guardrail_category(error_category)
        failure_state_tools = {"test_debug", "test_run"}
        scoped_test_run = self._scoped_test_run_status(
            tool_calls=tool_calls,
            failure_metadata=failure_metadata or {},
        )

        if not changed:
            missing.append("non_noop_edit")
        if changed and not (failure_state_tools & tool_set):
            missing.append("test_debug_or_test_run")
        if changed and tools and tools[0] not in failure_state_tools:
            missing.append("first_tool_test_debug_or_test_run")
        if changed and scoped_test_run["required"] and not scoped_test_run["scoped"]:
            missing.append("scoped_test_run")
        if changed and category in {"selector", "timing"} and not (
            {"browser_snapshot", "browser_generate_locator"} & tool_set
        ):
            missing.append("browser_snapshot_or_browser_generate_locator")
        if changed and category in {"auth", "test_data", "server_error", "product_bug", "connectivity", "not_found"} and not (
            {"browser_network_requests", "browser_console_messages"} & tool_set
        ):
            missing.append("browser_network_requests_or_browser_console_messages")

        assertion_removed = self._assertion_count(content_after) < self._assertion_count(content_before)
        fixme_before = self._has_test_fixme(content_before)
        fixme_explicit = self._has_test_fixme(content_after)
        newly_introduced_fixme = fixme_explicit and not fixme_before
        if assertion_removed and not (fixme_explicit and triage_allows_fixme):
            missing.append("assertion_preservation_or_explicit_test_fixme")
        if changed and newly_introduced_fixme and not triage_allows_fixme:
            missing.append("new_test_fixme_requires_non_healable_triage")

        added, removed = self._diff_counts(content_before, content_after)
        before_lines = max(len(content_before.splitlines()), 1)
        broad_rewrite = (added + removed) > max(80, int(before_lines * 0.4))
        evidence_tools = [
            tool
            for tool in tools
            if tool
            in {
                "test_run",
                "test_debug",
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
            "scoped_test_run": scoped_test_run,
            "mcp_evidence_tools_used": evidence_tools,
            "used_failure_state_tool": bool(
                {"test_debug", "browser_resume", "browser_snapshot"} & tool_set
            ),
            "assertion_removed": assertion_removed,
            "test_fixme_explicit": fixme_explicit,
            "newly_introduced_test_fixme": newly_introduced_fixme,
            "triage_allows_fixme": triage_allows_fixme,
            "broad_rewrite": broad_rewrite,
        }

    def _scoped_test_run_status(
        self,
        *,
        tool_calls: list[dict[str, Any]],
        failure_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        required_values = {
            "file": failure_metadata.get("file"),
            "project": failure_metadata.get("project"),
            "title": failure_metadata.get("title") or failure_metadata.get("full_title"),
        }
        required_values = {key: str(value) for key, value in required_values.items() if value}
        if not required_values:
            return {"required": False, "scoped": True, "missing": []}

        failure_state_call = next(
            (
                call
                for call in tool_calls
                if self._normalized_tool_name(call.get("tool") or call.get("name"))
                in {"test_debug", "test_run"}
            ),
            None,
        )
        if not failure_state_call:
            return {"required": True, "scoped": False, "missing": sorted(required_values)}

        call_input = failure_state_call.get("input") or failure_state_call.get("arguments") or {}
        missing = [
            key
            for key, value in required_values.items()
            if not self._tool_input_contains(call_input, value)
        ]
        return {"required": True, "scoped": not missing, "missing": missing}

    @classmethod
    def _tool_input_contains(cls, value: Any, expected: str) -> bool:
        expected_lower = expected.lower()
        expected_name = Path(expected).name.lower()
        if isinstance(value, str):
            lower = value.lower()
            return expected_lower in lower or expected_name in lower
        if isinstance(value, dict):
            return any(cls._tool_input_contains(item, expected) for item in value.values())
        if isinstance(value, list):
            return any(cls._tool_input_contains(item, expected) for item in value)
        return expected_lower in str(value).lower()

    def _evaluate_api_healer_guardrails(
        self,
        *,
        content_before: str,
        content_after: str,
    ) -> dict[str, Any]:
        """Reject API healer edits that weaken assertions or broadly rewrite intent."""
        missing: list[str] = []
        changed = content_before != content_after
        if not changed:
            missing.append("non_noop_edit")
        if "@playwright/test" not in content_after:
            missing.append("playwright_import")
        if "test(" not in content_after and "test.describe" not in content_after:
            missing.append("playwright_test")
        if "expect(" not in content_after and "test.fixme" not in content_after:
            missing.append("assertion_or_explicit_test_fixme")

        assertion_removed = self._assertion_count(content_after) < self._assertion_count(content_before)
        fixme_explicit = self._is_assertion_removal_allowed(content_after)
        if assertion_removed and not fixme_explicit:
            missing.append("assertion_preservation_or_explicit_test_fixme")

        added, removed = self._diff_counts(content_before, content_after)
        before_lines = max(len(content_before.splitlines()), 1)
        broad_rewrite = (added + removed) > max(80, int(before_lines * 0.4))
        if broad_rewrite and "test.fixme" not in content_after:
            missing.append("no_broad_rewrite_without_fixme")

        return {
            "guardrail_status": "failed" if missing else "passed",
            "missing_required_tools": missing,
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

    def _emit_handoff_event(
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
            logger.debug("Could not emit handoff agent run event %s: %s", event_type, exc)

    @staticmethod
    def _manifest_artifact_payload(manifest_file: Path, artifact_ids: list[str]) -> dict[str, Any]:
        manifest = load_manifest(manifest_file)
        artifacts = manifest.get("artifacts") if isinstance(manifest, dict) else {}
        payload: dict[str, Any] = {}
        if not isinstance(artifacts, dict):
            return payload
        for artifact_id in artifact_ids:
            item = artifacts.get(artifact_id)
            if not isinstance(item, dict):
                continue
            payload[artifact_id] = {
                "path": item.get("path"),
                "hash": item.get("hash") or item.get("current_hash"),
                "validation_status": item.get("validation_status"),
                "required": item.get("required"),
                "failure_reason": item.get("failure_reason"),
            }
        return payload

    @staticmethod
    def _manifest_artifact_hashes(manifest_file: Path, artifact_ids: list[str]) -> dict[str, str | None]:
        manifest = load_manifest(manifest_file)
        artifacts = manifest.get("artifacts") if isinstance(manifest, dict) else {}
        if not isinstance(artifacts, dict):
            return {artifact_id: None for artifact_id in artifact_ids}
        return {
            artifact_id: (
                artifacts.get(artifact_id, {}).get("hash")
                if isinstance(artifacts.get(artifact_id), dict)
                else None
            )
            for artifact_id in artifact_ids
        }

    def _build_healer_handoff_context(
        self,
        *,
        manifest_file: Path | None,
        planner_draft_script_path: Path | None = None,
        limit: int = 6000,
    ) -> str:
        lines: list[str] = []
        if manifest_file and manifest_file.exists():
            manifest = load_manifest(manifest_file)
            artifacts = manifest.get("artifacts") if isinstance(manifest, dict) else {}
            stages = manifest.get("stages") if isinstance(manifest, dict) else {}
            if isinstance(artifacts, dict):
                lines.append("## Handoff Manifest Context")
                for artifact_id in (
                    "planner_plan",
                    "planner_draft_script",
                    "generated_test",
                    "generator_self_heal",
                ):
                    artifact = artifacts.get(artifact_id)
                    if not isinstance(artifact, dict):
                        continue
                    lines.append(
                        "- "
                        f"{artifact_id}: status={artifact.get('validation_status') or 'unknown'} "
                        f"hash={artifact.get('hash') or artifact.get('current_hash') or 'unknown'} "
                        f"path={artifact.get('path')}"
                    )
            generator = stages.get("generator") if isinstance(stages, dict) else {}
            if isinstance(generator, dict) and generator.get("artifacts_consumed"):
                lines.append("Generator consumed artifacts:")
                for artifact_id, item in generator.get("artifacts_consumed", {}).items():
                    if isinstance(item, dict):
                        lines.append(
                            f"- {artifact_id}: {item.get('status')}"
                            + (f" ({item.get('reason')})" if item.get("reason") else "")
                        )

            draft_artifact = artifacts.get("planner_draft_script") if isinstance(artifacts, dict) else None
            if not planner_draft_script_path and isinstance(draft_artifact, dict) and draft_artifact.get("path"):
                planner_draft_script_path = Path(str(draft_artifact["path"]))

        if planner_draft_script_path and planner_draft_script_path.exists():
            try:
                draft = planner_draft_script_path.read_text()
                head = min(limit // 2, len(draft))
                tail = max(limit - head, 0)
                lines.extend(
                    [
                        "",
                        "## Planner Draft Script Context",
                        "Use this only as selector and wait-strategy evidence. Prefer the current failed browser state when it differs.",
                        "```typescript",
                        truncate_middle(draft, head=head, tail=tail),
                        "```",
                    ]
                )
            except OSError as exc:
                lines.append(f"Planner draft script could not be read: {exc}")

        return "\n".join(lines).strip()

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
        plan_path: Path | None = None,
        handoff_manifest_path: Path | None = None,
    ) -> dict:
        """Native healing: up to 3 attempts with test_run and diagnostic tools."""
        logger.info("Stage 4: Native Healing (up to 3 attempts)...")
        report_progress("healing", "Starting native healing...", healing_attempt=1)

        max_attempts = 3
        error_log = self._build_structured_failure_context(
            test_path=test_path, run_dir=run_dir, result=result
        )
        if plan_path and plan_path.exists():
            try:
                plan_text = plan_path.read_text()
                plan_selectors = extract_plan_selectors(plan_text, limit=15)
                if plan_selectors:
                    selector_excerpt = "\n".join(plan_selectors)
                    error_log = (
                        "## Planner-Verified Selectors (from live exploration before generation)\n"
                        f"{selector_excerpt}\n\n"
                        f"{error_log}"
                    )
            except OSError as exc:
                logger.warning(f"Could not read planner artifact {plan_path}: {exc}")
        healer_handoff_context = self._build_healer_handoff_context(
            manifest_file=handoff_manifest_path,
        )
        if healer_handoff_context:
            error_log = f"{healer_handoff_context}\n\n{error_log}"
        diagnosis_context = self.failure_triage_agent.condensed_context(diagnosis)
        failure_metadata = self._extract_failed_test_metadata(
            self._read_json_file(run_dir / "test-results.json"), test_path
        )
        current_error_category = (
            (diagnosis or {}).get("category")
            or categorize_error(result.error_summary or result.output[-2000:])
        )
        attempt_records: list[dict] = []

        def record_healer_manifest_attempt(
            *,
            attempt_number: int,
            status: str,
            attempt_record: dict[str, Any] | None = None,
            tool_calls: list[dict[str, Any]] | None = None,
            error_type: str | None = None,
        ) -> None:
            if not handoff_manifest_path:
                return
            record = attempt_record or {}
            calls = tool_calls or []
            record_attempt(
                handoff_manifest_path,
                "healer",
                stage_attempt=attempt_number,
                status=status,
                agent_session_id=getattr(
                    getattr(self.native_healer, "last_agent_result", None),
                    "session_id",
                    None,
                ),
                executor_mode="queue_or_direct",
                model_tier=getattr(self, "model_tier", None),
                timeout_seconds=int(os.environ.get("HEALER_ATTEMPT_TIMEOUT_SECONDS", "600")),
                error_type=error_type
                or getattr(getattr(self.native_healer, "last_agent_result", None), "error_type", None)
                or record.get("error_category"),
                tool_call_summary={
                    "count": len(calls),
                    "tools": [call.get("tool") or call.get("name") for call in calls],
                },
                input_artifact_hashes={
                    "generated_test_before": record.get("content_hash_before"),
                },
                output_artifact_hash=record.get("content_hash_after"),
                metadata={
                    "guardrail_status": record.get("guardrail_status"),
                    "failure_evidence_packet": record.get("failure_evidence_packet"),
                    "passed_after": record.get("passed_after"),
                    "error_summary": record.get("error_summary"),
                },
            )

        if handoff_manifest_path:
            record_stage(
                handoff_manifest_path,
                "healer",
                status="ready",
                metadata={
                    "browser": browser,
                    "failure_category": current_error_category,
                    "failed_test": failure_metadata,
                },
            )
            record_consumption(
                handoff_manifest_path,
                "healer",
                "generated_test",
                status="used" if test_path.exists() else "missing",
                metadata={"path": str(test_path)},
            )
            for artifact_id in (
                "planner_plan",
                "planner_draft_script",
                "generator_self_heal",
            ):
                artifact = load_manifest(handoff_manifest_path).get("artifacts", {}).get(artifact_id)
                if isinstance(artifact, dict):
                    artifact_path = Path(str(artifact.get("path") or ""))
                    record_consumption(
                        handoff_manifest_path,
                        "healer",
                        artifact_id,
                        status="used" if artifact_path.exists() else "missing",
                        metadata={
                            "path": str(artifact_path),
                            "validation_status": artifact.get("validation_status"),
                        },
                    )
            self._emit_handoff_event(
                "healer_handoff_ready",
                "Healer handoff context is ready.",
                payload={
                    "artifacts": self._manifest_artifact_payload(
                        handoff_manifest_path,
                        ["planner_plan", "planner_draft_script", "generated_test"],
                    ),
                    "failure_category": current_error_category,
                    "failed_test": failure_metadata,
                },
            )

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
                        failure_metadata=failure_metadata,
                        triage_allows_fixme=bool(
                            (diagnosis or {}).get("allow_fixme")
                            or (diagnosis or {}).get("fixme_allowed")
                            or (diagnosis or {}).get("non_healable")
                        ),
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
                                "test_debug",
                                "browser_resume",
                                "browser_snapshot",
                                "browser_generate_locator",
                                "browser_network_requests",
                                "browser_console_messages",
                            }
                        ],
                        "used_failure_state_tool": any(
                            call.get("tool")
                            in {"test_debug", "browser_resume", "browser_snapshot"}
                            for call in tool_calls
                        ),
                        "scoped_test_run": {"required": False, "scoped": True, "missing": []},
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
                    "scoped_test_run": guardrail.get("scoped_test_run"),
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
                record_healer_manifest_attempt(
                    attempt_number=attempt,
                    status="running",
                    attempt_record=attempt_record,
                    tool_calls=tool_calls,
                )

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
                    record_healer_manifest_attempt(
                        attempt_number=attempt,
                        status="guardrail_failed",
                        attempt_record=attempt_record,
                        tool_calls=tool_calls,
                        error_type="guardrail_failed",
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
                        "If `scoped_test_run` is listed, rerun the exact failed file, browser/project, "
                        "and title/grep from the Failed Test Target before editing.\n\n"
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
                        record_healer_manifest_attempt(
                            attempt_number=attempt,
                            status="passed",
                            attempt_record=attempt_record,
                            tool_calls=tool_calls,
                        )
                        self._record_healing_attempt(run_dir, test_path, attempt_records, attempt_record)
                        if handoff_manifest_path:
                            attempts_path = run_dir / "healing_attempts.json"
                            if attempts_path.exists():
                                record_artifact(
                                    handoff_manifest_path,
                                    "healing_attempts",
                                    attempts_path,
                                    kind="healing_attempts",
                                    producer_stage="healer",
                                    required=False,
                                    consumers=["reporting"],
                                    validation_status="valid",
                                )
                            record_stage(
                                handoff_manifest_path,
                                "healer",
                                status="passed",
                                metadata={"attempt": attempt},
                            )
                        self._write_run_metrics(
                            run_dir,
                            healing_started=True,
                            healing_attempts=attempt,
                            heal_rescued=True,
                        )
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
                        record_healer_manifest_attempt(
                            attempt_number=attempt,
                            status="failed",
                            attempt_record=attempt_record,
                            tool_calls=tool_calls,
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
                    record_healer_manifest_attempt(
                        attempt_number=attempt,
                        status="failed",
                        attempt_record=attempt_record,
                        tool_calls=tool_calls,
                        error_type="no_fix_produced",
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
                    f"Healer timed out on attempt {attempt}/{max_attempts} - continuing if attempts remain"
                )
                if handoff_manifest_path:
                    record_attempt(
                        handoff_manifest_path,
                        "healer",
                        stage_attempt=attempt,
                        status="timeout",
                        agent_session_id=getattr(
                            getattr(self.native_healer, "last_agent_result", None),
                            "session_id",
                            None,
                        ),
                        executor_mode="queue_or_direct",
                        model_tier=getattr(self, "model_tier", None),
                        timeout_seconds=int(
                            os.environ.get("HEALER_ATTEMPT_TIMEOUT_SECONDS", "600")
                        ),
                        error_type="timeout",
                        tool_call_summary={
                            "count": len(getattr(self.native_healer, "last_tool_calls", []) or []),
                        },
                        input_artifact_hashes={
                            "generated_test": self._content_hash(
                                test_path.read_text() if test_path.exists() else ""
                            )
                        },
                    )
                continue

            except Exception as e:
                error_attempt_record = {
                    "attempt": attempt,
                    "timestamp": datetime.now().isoformat(),
                    "error_category": "healer_error",
                    "error_summary": str(e)[:500],
                    "changed": False,
                    "passed_after": False,
                }
                record_healer_manifest_attempt(
                    attempt_number=attempt,
                    status="failed",
                    attempt_record=error_attempt_record,
                    tool_calls=getattr(self.native_healer, "last_tool_calls", []) or [],
                    error_type="healer_error",
                )
                self._record_healing_attempt(
                    run_dir,
                    test_path,
                    attempt_records,
                    error_attempt_record,
                )
                logger.warning(f"Healing error: {e}")

        logger.error(f"Native healing exhausted after {max_attempts} attempts")
        (run_dir / "status.txt").write_text("failed")
        self._write_run_metrics(
            run_dir,
            healing_started=True,
            healing_attempts=max_attempts,
            heal_rescued=False,
        )

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
        if handoff_manifest_path:
            attempts_path = run_dir / "healing_attempts.json"
            if attempts_path.exists():
                record_artifact(
                    handoff_manifest_path,
                    "healing_attempts",
                    attempts_path,
                    kind="healing_attempts",
                    producer_stage="healer",
                    required=False,
                    consumers=["reporting"],
                    validation_status="valid",
                )
            record_stage(
                handoff_manifest_path,
                "healer",
                status="exhausted",
                failure_reason=f"Failed after {max_attempts} native healing attempts",
                metadata={"attempts": max_attempts},
            )

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
        handoff_manifest_path: Path | None = None,
    ) -> dict:
        """
        Run the API-specific pipeline.

        Skips browser planning entirely - API tests generate code directly from spec.
        Uses lighter healing loop without browser MCP tools.
        """
        spec_file = Path(spec_path)
        handoff_manifest_path = handoff_manifest_path or init_manifest(run_dir, pipeline_type="api")
        if spec_file.exists():
            record_artifact(
                handoff_manifest_path,
                "resolved_spec",
                spec_file,
                kind="markdown_spec",
                producer_stage="pipeline",
                required=True,
                consumers=["api_generator"],
                validation_status="valid",
            )
        record_stage(
            handoff_manifest_path,
            "api_generator",
            status="running",
            metadata={"target_url": target_url},
        )

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
                handoff_manifest_path=handoff_manifest_path,
            )

            if not test_path or not test_path.exists():
                error_msg = "API generator failed to create test file"
                (run_dir / "status.txt").write_text("error")
                self._write_pipeline_error(run_dir, error_msg, "api_generation")
                record_stage(
                    handoff_manifest_path,
                    "api_generator",
                    status="failed",
                    failure_reason=error_msg,
                    metadata=getattr(self.api_generator, "last_handoff_consumption", {}),
                )
                self._write_run_metrics(run_dir, generation_success=False)
                return {
                    "success": False,
                    "error": error_msg,
                    "stage": "api_generation",
                    "test_type": "api",
                }

            validation_error = self._validate_generated_test_file(
                test_path=test_path,
                run_dir=run_dir,
                browser=browser,
                test_type="api",
            )
            record_artifact(
                handoff_manifest_path,
                "generated_api_test",
                test_path,
                kind="playwright_api_test",
                producer_stage="api_generator",
                required=True,
                consumers=["test_run", "api_healer", "reporting"],
                validation_status="pending_validation",
                metadata=getattr(self.api_generator, "last_handoff_consumption", {}),
            )
            validation_status = validate_artifact(
                handoff_manifest_path,
                "generated_api_test",
                validator=lambda _path: (validation_error is None, validation_error),
            )
            if validation_error:
                logger.error(validation_error)
                (run_dir / "status.txt").write_text("error")
                self._write_pipeline_error(
                    run_dir, validation_error, "api_generation_validation"
                )
                self._write_run_metrics(
                    run_dir,
                    generation_success=False,
                    failure_category="api_generation_validation",
                )
                record_stage(
                    handoff_manifest_path,
                    "api_generator",
                    status="failed",
                    failure_reason=validation_error,
                    metadata={
                        **getattr(self.api_generator, "last_handoff_consumption", {}),
                        "validation": validation_status,
                    },
                )
                return {
                    "success": False,
                    "error": validation_error,
                    "stage": "api_generation_validation",
                    "test_type": "api",
                }

            logger.info(f"API test generated: {test_path}")
            record_stage(
                handoff_manifest_path,
                "api_generator",
                status="ready",
                metadata={
                    **getattr(self.api_generator, "last_handoff_consumption", {}),
                    "test_path": str(test_path),
                    "validation": validation_status,
                },
            )
            self._emit_handoff_event(
                "generator_handoff_consumed",
                "API generator consumed spec handoff context.",
                payload={
                    "artifacts": self._manifest_artifact_payload(
                        handoff_manifest_path,
                        ["resolved_spec", "generated_api_test"],
                    ),
                    "consumption": getattr(self.api_generator, "last_handoff_consumption", {}),
                    "test_type": "api",
                    "validation": validation_status,
                },
            )
            self._write_run_metrics(
                run_dir,
                planner_success=True,
                generation_success=True,
            )

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
            record_stage(
                handoff_manifest_path,
                "test_run",
                status="running",
                metadata={"browser": browser, "test_path": str(test_path), "test_type": "api"},
            )
            record_consumption(
                handoff_manifest_path,
                "test_run",
                "generated_api_test",
                status="used",
                metadata={"path": str(test_path)},
            )

            result = self._run_test(str(test_path), str(run_dir), browser)

            if result.passed:
                logger.info("API test PASSED on first run!")
                (run_dir / "status.txt").write_text("passed")
                record_stage(
                    handoff_manifest_path,
                    "test_run",
                    status="passed",
                    metadata={"exit_code": result.exit_code, "test_type": "api"},
                )
                self._write_run_metrics(
                    run_dir,
                    initial_run_passed=True,
                    stable_first_pass=True,
                    healing_started=False,
                    healing_attempts=0,
                    heal_rescued=False,
                )
                return {
                    "success": True,
                    "test_path": str(test_path),
                    "attempts": 0,
                    "stage": "completed",
                    "test_type": "api",
                }

            logger.error(f"API test FAILED: {result.error_summary}")
            api_failure_category = categorize_error(result.error_summary or result.output[-2000:])
            record_stage(
                handoff_manifest_path,
                "test_run",
                status="failed",
                failure_reason=result.error_summary or result.output[-500:],
                metadata={
                    "exit_code": result.exit_code,
                    "failure_category": api_failure_category,
                    "test_type": "api",
                },
            )
            self._emit_handoff_event(
                "test_run_handoff_failed",
                "Generated API test failed and is ready for healer handoff.",
                level="warning",
                payload={
                    "artifacts": self._manifest_artifact_payload(
                        handoff_manifest_path,
                        ["generated_api_test", "resolved_spec"],
                    ),
                    "failure_category": api_failure_category,
                    "error_summary": result.error_summary,
                    "test_type": "api",
                },
            )
            self._write_run_metrics(
                run_dir,
                initial_run_passed=False,
                stable_first_pass=False,
                failure_category=api_failure_category,
            )

            # Stage 3: API Healing
            logger.info("Stage 3: API Test Healing (up to 3 attempts)...")
            report_progress(
                "healing", "Starting API test healing...", healing_attempt=1
            )

            max_heal_attempts = 3
            error_log = self._build_structured_failure_context(
                test_path=test_path, run_dir=run_dir, result=result
            )
            attempt_records: list[dict[str, Any]] = []
            record_stage(
                handoff_manifest_path,
                "api_healer",
                status="ready",
                metadata={"failure_category": api_failure_category, "test_path": str(test_path)},
            )
            record_consumption(
                handoff_manifest_path,
                "api_healer",
                "generated_api_test",
                status="used",
                metadata={"path": str(test_path)},
            )
            self._emit_handoff_event(
                "healer_handoff_ready",
                "API healer handoff context is ready.",
                payload={
                    "artifacts": self._manifest_artifact_payload(
                        handoff_manifest_path,
                        ["generated_api_test", "resolved_spec"],
                    ),
                    "failure_category": api_failure_category,
                    "test_type": "api",
                },
            )

            for attempt in range(1, max_heal_attempts + 1):
                logger.info(f"Healing attempt {attempt}/{max_heal_attempts}...")
                report_progress(
                    "healing",
                    f"API healing attempt {attempt}/{max_heal_attempts}...",
                    healing_attempt=attempt,
                )

                try:
                    try:
                        content_before = test_path.read_text()
                    except OSError:
                        content_before = ""
                    fixed_code = await self.api_healer.heal_test(
                        str(test_path),
                        error_log,
                        spec_content,
                        failure_context=error_log,
                    )

                    if fixed_code:
                        content_after = fixed_code
                        guardrail = self._evaluate_api_healer_guardrails(
                            content_before=content_before,
                            content_after=content_after,
                        )
                        attempt_record = {
                            "attempt": attempt,
                            "timestamp": datetime.now().isoformat(),
                            "content_hash_before": self._content_hash(content_before),
                            "content_hash_after": self._content_hash(content_after),
                            "changed": content_after != content_before,
                            "diff_stat": self._diff_stat(content_before, content_after),
                            "guardrail_status": guardrail.get("guardrail_status"),
                            "missing_required_tools": guardrail.get("missing_required_tools", []),
                            "assertion_removed": guardrail.get("assertion_removed", False),
                            "broad_rewrite": guardrail.get("broad_rewrite", False),
                        }
                        if guardrail.get("guardrail_status") == "failed":
                            try:
                                test_path.write_text(content_before)
                                attempt_record["reverted"] = True
                            except OSError as exc:
                                attempt_record["revert_error"] = str(exc)[:300]
                            attempt_record.update(
                                {
                                    "error_category": "guardrail_failed",
                                    "error_summary": "API healer edit rejected by guardrail",
                                    "passed_after": False,
                                }
                            )
                            self._record_healing_attempt(run_dir, test_path, attempt_records, attempt_record)
                            error_log = (
                                "## Previous API Healer Edit Rejected By Guardrail\n\n"
                                f"Missing required evidence: {', '.join(guardrail.get('missing_required_tools', []))}\n\n"
                                + error_log
                            )
                            continue

                        logger.info("Re-running healed API test...")
                        result = self._run_test(str(test_path), str(run_dir), browser)

                        if result.passed:
                            logger.info(
                                f"Healed API test PASSED (after {attempt} attempt(s))!"
                            )
                            (run_dir / "status.txt").write_text("passed")
                            attempt_record.update(
                                {"error_category": "passed", "error_summary": "", "passed_after": True}
                            )
                            self._record_healing_attempt(run_dir, test_path, attempt_records, attempt_record)
                            self._write_run_metrics(
                                run_dir,
                                healing_started=True,
                                healing_attempts=attempt,
                                heal_rescued=True,
                            )

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
                            failure_text = result.error_summary or result.output[-2000:]
                            attempt_record.update(
                                {
                                    "error_category": categorize_error(failure_text),
                                    "error_summary": failure_text[:500],
                                    "passed_after": False,
                                }
                            )
                            self._record_healing_attempt(run_dir, test_path, attempt_records, attempt_record)
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
                        self._record_healing_attempt(
                            run_dir,
                            test_path,
                            attempt_records,
                            {
                                "attempt": attempt,
                                "timestamp": datetime.now().isoformat(),
                                "changed": False,
                                "error_category": "no_fix_produced",
                                "error_summary": "API healer returned no code",
                                "passed_after": False,
                            },
                        )
                        logger.warning("Healer returned no code")

                except Exception as e:
                    self._record_healing_attempt(
                        run_dir,
                        test_path,
                        attempt_records,
                        {
                            "attempt": attempt,
                            "timestamp": datetime.now().isoformat(),
                            "changed": False,
                            "error_category": "healer_error",
                            "error_summary": str(e)[:500],
                            "passed_after": False,
                        },
                    )
                    logger.warning(f"Healing error: {e}")

            logger.error(f"API healing exhausted after {max_heal_attempts} attempts")
            (run_dir / "status.txt").write_text("failed")
            self._write_run_metrics(
                run_dir,
                healing_started=True,
                healing_attempts=max_heal_attempts,
                heal_rescued=False,
            )

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
        if storage_state_path is None:
            candidate = run_dir / "browser-auth-storage-state.json"
            if candidate.exists():
                storage_state_path = candidate
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

        native_planner = getattr(self, "native_planner", None)
        if native_planner is not None:
            native_planner.cwd = run_dir
            native_planner.session_dir = run_dir
        native_generator = getattr(self, "native_generator", None)
        if native_generator is not None:
            native_generator.cwd = run_dir
        native_healer = getattr(self, "native_healer", None)
        if native_healer is not None:
            native_healer.cwd = run_dir
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
