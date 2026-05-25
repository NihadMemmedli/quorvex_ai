"""
Auto Pilot Pipeline - Autonomous End-to-End Test Engineering

State machine orchestrator that runs 6 phases sequentially:
1. Exploration   - Discover app structure (one session per entry URL)
2. Requirements  - Extract requirements from exploration data
3. Test Ideas    - Prioritize traceable, spec-ready test ideas
4. Spec Generation - Generate test specs from test ideas (priority-ordered)
5. Test Generation - Generate and validate test code (parallel, browser pool bounded)
6. Reporting     - Generate RTM and coverage report

The pipeline pauses at strategic checkpoints (between phases) to ask the user
questions via the question system. If the user does not answer within the
configured auto-continue timeout, the default answer is used and the pipeline
proceeds automatically.

State Machine:
    pending -> running -> running (next phase)
                 |                   |
                 +-> awaiting_input -+-> running
                 |
                 +-> paused -> running
                 |
                 +-> completed
                 +-> failed
                 +-> cancelled
"""

import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlmodel import Session, select

from orchestrator.ai.context import SOURCE_OBSERVED
from orchestrator.ai.validation import (
    is_valid_flow,
    is_valid_issue,
    is_valid_transition,
    should_gate_exploration,
    validate_exploration_result,
)

logger = logging.getLogger(__name__)

# Priority ordering for spec generation (highest first)
PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class AutoPilotConfig:
    """Configuration for Auto Pilot pipeline."""

    entry_urls: list[str]
    project_id: str = "default"
    login_url: str | None = None
    credentials: dict[str, str] | None = None
    test_data: dict[str, Any] | None = None
    instructions: str | None = None

    # Exploration settings
    strategy: str = "goal_directed"
    max_interactions: int = 50
    max_depth: int = 10
    timeout_minutes: int = 30

    # Pipeline settings
    reactive_mode: bool = True  # Ask questions at checkpoints
    auto_continue_hours: int = 24  # Auto-continue timeout
    priority_threshold: str = "low"  # Minimum priority for specs
    max_specs: int = 50  # Max specs to generate
    parallel_generation: int = 2  # Concurrent test generations
    hybrid_healing: bool = False  # Use hybrid healing mode


class AutoPilotPipeline:
    """
    Auto Pilot: Autonomous end-to-end test engineering pipeline.

    Runs 6 phases sequentially:
    1. Exploration     - Discover app structure (one session per URL)
    2. Requirements    - Extract requirements from exploration data
    3. Test Ideas      - Generate traceable test ideas from requirements/exploration
    4. Spec Generation - Generate test specs from test ideas (priority-ordered)
    5. Test Generation - Generate and validate test code (parallel, browser pool bounded)
    6. Reporting       - Generate RTM and coverage report
    """

    PHASES = [
        ("exploration", 0.25),
        ("requirements", 0.10),
        ("test_ideas", 0.10),
        ("spec_generation", 0.18),
        ("test_generation", 0.32),
        ("reporting", 0.10),
    ]

    def __init__(self, session_id: str, project_id: str = "default"):
        self.session_id = session_id
        self.project_id = project_id
        self._cancelled = asyncio.Event()
        self._paused = asyncio.Event()
        self._paused.set()  # Not paused initially
        self._question_answered = asyncio.Event()
        self._current_question_id: int | None = None
        self._config: AutoPilotConfig | None = None
        self._test_tasks: dict[int, asyncio.Task] = {}
        self._checkpoint_answers: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public control methods
    # ------------------------------------------------------------------

    def cancel(self):
        """Cancel the running pipeline. Safe to call from any coroutine."""
        self._cancelled.set()
        self._paused.set()  # Unblock if paused
        self._question_answered.set()  # Unblock if waiting for answer

    def cancel_test_task(self, task_id: int):
        """Cancel a specific test generation task."""
        task = self._test_tasks.get(task_id)
        if task and not task.done():
            task.cancel()
            logger.info(f"Cancelled test task {task_id} in session {self.session_id}")
        else:
            logger.warning(
                f"Test task {task_id} not found or already done in session {self.session_id}"
            )

    def pause(self):
        """Hard-pause the pipeline and cancel tracked test-generation tasks."""
        self._paused.clear()
        for task_id, task in list(self._test_tasks.items()):
            if not task.done():
                task.cancel()
                logger.info(
                    f"Paused Auto Pilot by cancelling test task {task_id} in session {self.session_id}"
                )

    def resume(self):
        """Resume a paused pipeline."""
        self._paused.set()

    def answer_question(self, question_id: int, answer_text: str):
        """Called by API when user answers. Unblocks the pipeline."""
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotQuestion

        with Session(engine) as db:
            question = db.get(AutoPilotQuestion, question_id)
            if question:
                question.status = "answered"
                question.answer_text = answer_text
                question.answered_at = datetime.utcnow()
                db.add(question)
                db.commit()

        self._question_answered.set()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self, config: AutoPilotConfig) -> dict[str, Any]:
        """
        Execute the Auto Pilot pipeline.

        Checks session.phases_completed to support resuming interrupted runs.
        For phases that were interrupted mid-execution (spec_generation,
        test_generation), only pending/failed sub-tasks are processed.

        Args:
            config: Pipeline configuration

        Returns:
            Summary dict with results from all phases
        """
        self._config = config
        summary: dict[str, Any] = {
            "session_id": self.session_id,
            "status": "running",
            "phases": {},
        }

        self._update_session_status("running")
        self._update_session_field("started_at", datetime.utcnow())

        # Load already-completed phases for resume support
        completed_phases = self._get_completed_phases()

        phase_runners = [
            ("exploration", self._run_exploration_phase),
            ("requirements", self._run_requirements_phase),
            ("test_ideas", self._run_test_ideas_phase),
            ("spec_generation", self._run_spec_generation_phase),
            ("test_generation", self._run_test_generation_phase),
            ("reporting", self._run_reporting_phase),
        ]

        cumulative_weight = 0.0

        for phase_name, runner in phase_runners:
            # Check cancellation
            if self._cancelled.is_set():
                self._update_session_status("cancelled")
                self._update_live_browser_state(
                    {
                        "active": False,
                        "phase": phase_name,
                        "status": "cancelled",
                        "message": "Auto Pilot cancelled",
                    }
                )
                summary["status"] = "cancelled"
                return summary

            # Wait if paused
            await self._wait_if_paused()

            # Find phase weight for progress calculation
            phase_weight = next(w for name, w in self.PHASES if name == phase_name)

            # Skip already-completed phases (resume support)
            if phase_name in completed_phases:
                logger.info(f"Skipping already-completed phase: {phase_name}")
                cumulative_weight += phase_weight
                self._update_overall_progress(cumulative_weight)
                summary["phases"][phase_name] = {
                    "status": "skipped (already completed)"
                }
                continue

            # Update current phase
            self._update_session_field("current_phase", phase_name)
            if phase_name not in ("exploration", "test_generation"):
                self._update_live_browser_state(
                    {
                        "active": False,
                        "phase": phase_name,
                        "activity_label": phase_name.replace("_", " ").title(),
                        "status": "idle",
                        "message": "Current phase does not use the live browser",
                    }
                )
            logger.info(f"{'=' * 60}")
            logger.info(f"AUTO PILOT - Phase: {phase_name}")
            logger.info(f"{'=' * 60}")

            # Create/update phase record
            phase_record_id = self._create_phase_record(phase_name)

            try:
                result = await runner(config, phase_record_id)
                summary["phases"][phase_name] = result
                if not self._phase_has_resumable_output(phase_name, result):
                    raise RuntimeError(self._phase_output_error(phase_name, result))

                # Mark phase completed
                self._complete_phase_record(phase_record_id, result)
                self._add_completed_phase(phase_name)
                cumulative_weight += phase_weight
                self._update_overall_progress(cumulative_weight)

                logger.info(
                    f"Phase {phase_name} completed: {result.get('status', 'ok')}"
                )

            except asyncio.CancelledError:
                if not self._paused.is_set() and not self._cancelled.is_set():
                    self._update_phase_step(phase_record_id, "Paused by user")
                    self._update_session_status("paused")
                    summary["status"] = "paused"
                    summary["paused_phase"] = phase_name
                    return summary

                self._fail_phase_record(phase_record_id, "Cancelled")
                self._update_session_status("cancelled")
                self._update_live_browser_state(
                    {
                        "active": False,
                        "phase": phase_name,
                        "status": "cancelled",
                        "message": "Auto Pilot cancelled",
                    }
                )
                summary["status"] = "cancelled"
                return summary

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Phase {phase_name} failed: {error_msg}", exc_info=True)
                self._fail_phase_record(phase_record_id, error_msg)
                self._update_session_status("failed", error=error_msg)
                self._update_live_browser_state(
                    {
                        "active": False,
                        "phase": phase_name,
                        "status": "failed",
                        "message": error_msg[:300],
                    }
                )
                summary["status"] = "failed"
                summary["error"] = error_msg
                summary["failed_phase"] = phase_name
                return summary

        # All phases completed
        self._update_session_status("completed")
        self._update_session_field("completed_at", datetime.utcnow())
        self._update_overall_progress(1.0)
        self._update_live_browser_state(
            {
                "active": False,
                "phase": "completed",
                "activity_label": "Auto Pilot completed",
                "status": "completed",
                "message": "Auto Pilot completed",
            }
        )
        summary["status"] = "completed"

        logger.info("=" * 60)
        logger.info("AUTO PILOT - Pipeline Completed")
        logger.info("=" * 60)

        return summary

    # ------------------------------------------------------------------
    # Phase 1: Exploration
    # ------------------------------------------------------------------

    async def _run_exploration_phase(
        self, config: AutoPilotConfig, phase_id: int
    ) -> dict[str, Any]:
        """Explore each entry URL to discover app structure."""
        exploration_ids: list[str] = []
        exploration_quality: list[dict[str, Any]] = []
        exploration_quality_by_session: dict[str, dict[str, Any]] = {}
        total_pages = 0
        total_flows = 0
        total_transitions = 0
        total_api_endpoints = 0

        async def run_pass(
            pass_label: str, max_interactions: int, strategy: str, start_index: int = 0
        ):
            nonlocal total_pages, total_flows, total_transitions, total_api_endpoints
            for idx, url in enumerate(config.entry_urls):
                if self._cancelled.is_set():
                    break

                display_idx = start_index + idx
                self._update_phase_step(
                    phase_id,
                    f"Exploring URL {idx + 1}/{len(config.entry_urls)} ({pass_label}): {url}",
                    items_total=len(config.entry_urls),
                    items_completed=idx,
                )

                result = await self._explore_url(
                    config=config,
                    url=url,
                    url_index=display_idx,
                    pass_label=pass_label,
                    max_interactions=max_interactions,
                    strategy=strategy,
                )
                if not result:
                    continue

                exploration_ids.append(result.session_id)
                exploration_quality.append(result.quality_summary or {})
                exploration_quality_by_session[result.session_id] = {
                    "quality": result.quality_summary or {},
                    "validation": result.validation_summary or {},
                    "provenance_source": result.provenance_source,
                    "quality_score": result.quality_score,
                }
                total_pages += result.pages_discovered
                total_flows += len(result.flows)
                total_transitions += len(result.transitions)
                total_api_endpoints += len(result.api_endpoints)

                logger.info(
                    "Exploration %s for %s done: %s pages, %s flows",
                    pass_label,
                    url,
                    result.pages_discovered,
                    len(result.flows),
                )

        await run_pass("initial", config.max_interactions, config.strategy)

        auto_retried = False
        retry_reason = self._auto_retry_reason(
            total_pages=total_pages,
            total_flows=total_flows,
            total_transitions=total_transitions,
            total_api_endpoints=total_api_endpoints,
        )
        if exploration_ids and retry_reason:
            auto_retried = True
            retry_interactions = min(
                200, max(config.max_interactions * 2, config.max_interactions + 50, 100)
            )
            logger.info(
                "Exploration evidence is weak (%s pages, %s flows); retrying with %s interactions",
                total_pages,
                total_flows,
                retry_interactions,
            )
            self._merge_session_config(
                {
                    "ai_quality": {
                        "exploration": {
                            "retry_reason": retry_reason,
                            "auto_retry_triggered": True,
                        }
                    }
                }
            )
            self._update_phase_step(
                phase_id,
                "Exploration found limited evidence; retrying with more interactions",
                items_total=len(config.entry_urls),
                items_completed=0,
            )
            await run_pass(
                "auto_retry",
                retry_interactions,
                "breadth_first",
                start_index=len(exploration_ids),
            )

        self._update_session_list("exploration_session_ids", exploration_ids)
        self._update_session_field("total_pages_discovered", total_pages)
        self._update_session_field("total_flows_discovered", total_flows)
        self._merge_session_config(
            {
                "ai_quality": {
                    "exploration": {
                        "sessions": exploration_quality,
                        "min_quality_score": min(
                            [
                                q.get("quality_score", 0)
                                for q in exploration_quality
                                if q
                            ]
                            or [0]
                        ),
                        "degraded_mode": any(
                            q.get("degraded_mode") for q in exploration_quality if q
                        ),
                        "by_session": exploration_quality_by_session,
                    }
                }
            }
        )

        self._update_phase_step(
            phase_id,
            "Exploration complete",
            items_total=len(config.entry_urls),
            items_completed=len(config.entry_urls),
        )

        # Ask question after first exploration if reactive_mode
        if config.reactive_mode and exploration_ids:
            answer = await self._ask_exploration_checkpoint(
                config=config,
                exploration_ids=exploration_ids,
                total_pages=total_pages,
                total_flows=total_flows,
            )
            if "re-explore" in answer.lower() or "reexplore" in answer.lower():
                retry_interactions = min(
                    200,
                    max(config.max_interactions * 2, config.max_interactions + 50, 100),
                )
                await run_pass(
                    "user_reexplore",
                    retry_interactions,
                    "breadth_first",
                    start_index=len(exploration_ids),
                )
                self._update_session_list("exploration_session_ids", exploration_ids)
                self._update_session_field("total_pages_discovered", total_pages)
                self._update_session_field("total_flows_discovered", total_flows)
                if config.reactive_mode:
                    await self._ask_exploration_checkpoint(
                        config=config,
                        exploration_ids=exploration_ids,
                        total_pages=total_pages,
                        total_flows=total_flows,
                    )

        self._merge_session_config(
            {
                "ai_quality": {
                    "exploration": {
                        "by_session": exploration_quality_by_session,
                    }
                }
            }
        )

        return {
            "status": "completed",
            "exploration_ids": exploration_ids,
            "total_pages": total_pages,
            "total_flows": total_flows,
            "auto_retried": auto_retried,
            "quality": exploration_quality,
        }

    async def _explore_url(
        self,
        config: AutoPilotConfig,
        url: str,
        url_index: int,
        pass_label: str,
        max_interactions: int,
        strategy: str,
    ):
        """Run one stored exploration attempt for one URL."""
        from orchestrator.services.browser_pool import OperationType, get_browser_pool
        from orchestrator.services.load_test_lock import check_system_available
        from orchestrator.workflows.app_explorer import AppExplorer, ExplorationConfig

        additional_instructions = config.instructions
        if pass_label != "initial":
            retry_instructions = self._coverage_retry_instructions(pass_label)
            additional_instructions = (
                f"{config.instructions}\n\n{retry_instructions}"
                if config.instructions
                else retry_instructions
            )

        explore_config = ExplorationConfig(
            entry_url=url,
            max_interactions=max_interactions,
            max_depth=config.max_depth,
            strategy=strategy,
            timeout_minutes=config.timeout_minutes,
            credentials=config.credentials,
            login_url=config.login_url,
            additional_instructions=additional_instructions,
        )

        safe_label = re.sub(r"[^a-zA-Z0-9_]+", "_", pass_label).strip("_") or "pass"
        explore_session_id = f"{self.session_id}_explore_{url_index}_{safe_label}_{datetime.now().strftime('%H%M%S')}"
        self._update_live_browser_state(
            {
                "active": True,
                "phase": "exploration",
                "activity_label": f"Exploring {url}",
                "exploration_session_id": explore_session_id,
                "url": url,
                "status": "starting",
                "message": "Waiting for browser slot",
                "tool_calls": 0,
                "browser_tool_calls": 0,
                "interactions": 0,
                "last_tool": "",
                "last_tool_label": "",
                "recent_tools": [],
            }
        )

        await check_system_available("autopilot_exploration")

        pool = await get_browser_pool()
        async with pool.browser_slot(
            request_id=f"autopilot_{explore_session_id}",
            operation_type=OperationType.AUTOPILOT,
            description=f"AutoPilot exploration: {url}",
        ) as acquired:
            if not acquired:
                logger.warning(
                    f"Failed to acquire browser slot for exploration of {url}"
                )
                return None

            self._update_live_browser_state(
                {
                    "active": True,
                    "phase": "exploration",
                    "activity_label": f"Exploring {url}",
                    "exploration_session_id": explore_session_id,
                    "url": url,
                    "status": "running",
                    "message": "Browser slot acquired",
                }
            )

            def on_task_enqueued(task_id: str) -> None:
                self._update_live_browser_state(
                    {
                        "active": True,
                        "phase": "exploration",
                        "activity_label": f"Exploring {url}",
                        "exploration_session_id": explore_session_id,
                        "agent_task_id": task_id,
                        "status": "queued",
                        "message": "Agent task queued for worker",
                    }
                )

            def on_tool_use(tool_name: str, tool_input: dict[str, Any]) -> None:
                self._record_live_tool_use(
                    tool_name,
                    {
                        "active": True,
                        "phase": "exploration",
                        "activity_label": f"Exploring {url}",
                        "exploration_session_id": explore_session_id,
                        "status": "tool_use",
                        "message": f"Using {self._short_tool_name(tool_name)}",
                        "last_tool_input": tool_input,
                    },
                )

            def on_progress(progress: dict[str, Any]) -> None:
                last_tool = str(progress.get("last_tool") or "")
                patch = {
                    **progress,
                    "active": True,
                    "phase": "exploration",
                    "activity_label": f"Exploring {url}",
                    "exploration_session_id": explore_session_id,
                    "status": progress.get("phase") or "running",
                    "message": (
                        f"Using {self._short_tool_name(last_tool)}"
                        if last_tool
                        else "Agent is running"
                    ),
                }
                if last_tool:
                    self._record_live_tool_use(last_tool, patch)
                else:
                    self._update_live_browser_state(patch)

            explorer = AppExplorer(
                project_id=config.project_id,
                on_task_enqueued=on_task_enqueued,
                on_progress=on_progress,
                on_tool_use=on_tool_use,
                owner_type="autopilot",
                owner_id=self.session_id,
                owner_label=f"AutoPilot {self.session_id}",
            )
            result = await explorer.explore(explore_config, explore_session_id)
            self._store_exploration_results(
                explore_session_id, result, config.project_id
            )
            if result.status not in {"completed", "completed_partial"} or not (
                result.transitions
                or result.flows
                or result.api_endpoints
                or result.pages
            ):
                raise RuntimeError(
                    result.error_message
                    or "Explorer did not produce verified browser exploration records"
                )
            return result

    def _coverage_retry_instructions(self, pass_label: str) -> str:
        """Extra instructions used when the first exploration pass was too sparse."""
        return f"""## Coverage Retry Instructions ({pass_label})
The previous pass found many pages but too few meaningful flows. Optimize this pass for coverage quality:
- Emit one `page` JSON record for every unique page/state before moving on.
- For each distinct page type, identify at least one concrete user journey and emit a `flow` JSON record.
- Treat browsing from listing pages to detail pages, opening service pages, using tabs, language switching, filters/search, and form validation as separate flows when observed.
- Prefer concise, evidence-backed flows over generic availability checks.
- Do not spend the retry budget repeatedly inspecting the same URL unless it reveals a new form, action, tab, filter, or detail route.
"""

    async def _ask_exploration_checkpoint(
        self,
        config: AutoPilotConfig,
        exploration_ids: list[str],
        total_pages: int,
        total_flows: int,
    ) -> str:
        flow_names = self._get_discovered_flow_names(exploration_ids, config.project_id)
        return await self._ask_question_and_wait(
            phase_name="exploration",
            question_type="review_exploration",
            question_text=(
                f"Exploration discovered {total_pages} pages and {total_flows} flows "
                f"across {len(config.entry_urls)} URL(s). "
                f"Discovered flows: {', '.join(flow_names[:15])}. "
                f"Would you like to proceed with requirements generation?"
            ),
            context={
                "total_pages": total_pages,
                "total_flows": total_flows,
                "flow_names": flow_names[:30],
                "exploration_ids": exploration_ids,
            },
            suggested_answers=[
                "Proceed with all discovered flows",
                "Re-explore with more interactions",
                "Skip some flows and proceed",
            ],
            default_answer="Proceed with all discovered flows",
        )

    def _is_weak_exploration(self, total_pages: int, total_flows: int) -> bool:
        """Return True when exploration evidence is too thin for normal generation."""
        if total_pages <= 0:
            return total_flows == 0
        if total_flows == 0:
            return True
        if total_pages >= 10:
            return total_flows < max(3, total_pages // 8)
        if total_pages >= 5:
            return total_flows < 2
        return False

    def _auto_retry_reason(
        self,
        *,
        total_pages: int,
        total_flows: int,
        total_transitions: int,
        total_api_endpoints: int,
    ) -> str | None:
        """Retry only when the browser pass produced no usable evidence at all."""
        if total_pages or total_flows or total_transitions or total_api_endpoints:
            return None
        return "no_usable_exploration_evidence"

    # ------------------------------------------------------------------
    # Phase 2: Requirements
    # ------------------------------------------------------------------

    async def _run_requirements_phase(
        self, config: AutoPilotConfig, phase_id: int
    ) -> dict[str, Any]:
        """Extract requirements from exploration data."""
        from orchestrator.workflows.requirements_generator import RequirementsGenerator

        exploration_ids = self._get_session_exploration_ids()
        if not exploration_ids:
            logger.warning("No exploration sessions found, skipping requirements phase")
            return {"status": "skipped", "reason": "no_explorations"}
        usable_exploration_ids = self._filter_exploration_ids_by_quality(
            exploration_ids
        )
        if not usable_exploration_ids:
            logger.warning(
                "No reliable exploration sessions found, skipping requirements phase"
            )
            self._merge_session_config(
                {
                    "ai_quality": {
                        "requirements": {
                            "gated": True,
                            "reason": "no_reliable_exploration_sessions",
                            "input_exploration_ids": exploration_ids,
                        }
                    }
                }
            )
            return {
                "status": "skipped",
                "reason": "quality_gate",
                "input_exploration_ids": exploration_ids,
            }
        if len(usable_exploration_ids) != len(exploration_ids):
            logger.info(
                "Quality gate filtered explorations for requirements: %s -> %s",
                exploration_ids,
                usable_exploration_ids,
            )
            exploration_ids = usable_exploration_ids

        generator = RequirementsGenerator(project_id=config.project_id)
        all_requirements = []

        for idx, explore_id in enumerate(exploration_ids):
            if self._cancelled.is_set():
                break

            self._update_phase_step(
                phase_id,
                f"Generating requirements from exploration {idx + 1}/{len(exploration_ids)}",
                items_total=len(exploration_ids),
                items_completed=idx,
            )

            try:
                result = await generator.generate_from_exploration(explore_id)
                all_requirements.extend(result.requirements)
                logger.info(
                    f"Generated {result.total_requirements} requirements from exploration {explore_id}"
                )
            except Exception as e:
                logger.warning(f"Requirements generation failed for {explore_id}: {e}")

        self._update_session_field(
            "total_requirements_generated", len(all_requirements)
        )

        self._update_phase_step(
            phase_id,
            "Requirements generation complete",
            items_total=len(exploration_ids),
            items_completed=len(exploration_ids),
        )

        # Ask question about generated requirements if reactive_mode
        if config.reactive_mode and all_requirements:
            req_summaries = [
                {"code": r.req_code, "title": r.title, "priority": r.priority}
                for r in all_requirements[:20]
            ]
            await self._ask_question_and_wait(
                phase_name="requirements",
                question_type="review_requirements",
                question_text=(
                    f"Generated {len(all_requirements)} requirements. "
                    f"Priority breakdown: "
                    f"{sum(1 for r in all_requirements if r.priority == 'critical')} critical, "
                    f"{sum(1 for r in all_requirements if r.priority == 'high')} high, "
                    f"{sum(1 for r in all_requirements if r.priority == 'medium')} medium, "
                    f"{sum(1 for r in all_requirements if r.priority == 'low')} low. "
                    f"Proceed with test idea generation?"
                ),
                context={
                    "total": len(all_requirements),
                    "requirements_preview": req_summaries,
                },
                suggested_answers=[
                    "Proceed with all requirements",
                    "Focus on critical and high only",
                    "Skip low priority",
                ],
                default_answer="Proceed with all requirements",
            )

        return {
            "status": "completed",
            "total_requirements": len(all_requirements),
        }

    # ------------------------------------------------------------------
    # Phase 3: Test Ideas
    # ------------------------------------------------------------------

    async def _run_test_ideas_phase(
        self, config: AutoPilotConfig, phase_id: int
    ) -> dict[str, Any]:
        """Generate traceable test ideas and create spec tasks from them."""
        from orchestrator.workflows.test_idea_generator import TestIdeaGenerator

        exploration_ids = self._get_session_exploration_ids()
        if not exploration_ids:
            logger.warning("No exploration sessions found, skipping test idea phase")
            return {"status": "skipped", "reason": "no_explorations"}
        usable_exploration_ids = self._filter_exploration_ids_by_quality(
            exploration_ids
        )
        if not usable_exploration_ids:
            logger.warning(
                "No reliable exploration sessions found, skipping test idea phase"
            )
            self._merge_session_config(
                {
                    "ai_quality": {
                        "test_ideas": {
                            "gated": True,
                            "reason": "no_reliable_exploration_sessions",
                            "input_exploration_ids": exploration_ids,
                        }
                    }
                }
            )
            return {
                "status": "skipped",
                "reason": "quality_gate",
                "input_exploration_ids": exploration_ids,
            }
        if len(usable_exploration_ids) != len(exploration_ids):
            logger.info(
                "Quality gate filtered explorations for test ideas: %s -> %s",
                exploration_ids,
                usable_exploration_ids,
            )
            exploration_ids = usable_exploration_ids

        generator = TestIdeaGenerator(project_id=config.project_id)
        all_ideas = []

        for idx, explore_id in enumerate(exploration_ids):
            if self._cancelled.is_set():
                break

            self._update_phase_step(
                phase_id,
                f"Generating test ideas from exploration {idx + 1}/{len(exploration_ids)}",
                items_total=len(exploration_ids),
                items_completed=idx,
            )

            try:
                result = await generator.generate_from_exploration(explore_id)
                all_ideas.extend(result.ideas)
                logger.info(
                    f"Generated {result.total_ideas} test ideas from exploration {explore_id}"
                )
            except Exception as e:
                logger.warning(f"Test idea generation failed for {explore_id}: {e}")

        requirements = self._get_requirements_for_explorations(
            config.project_id, exploration_ids
        )
        expected_spec_tasks = self._count_unique_requirement_targets(requirements)
        if all_ideas:
            self._create_spec_tasks_from_test_ideas(all_ideas)
            if requirements and self._count_spec_tasks() < expected_spec_tasks:
                self._create_spec_tasks_from_requirements(requirements)
        elif not self._has_spec_tasks():
            self._create_spec_tasks_from_requirements(requirements)

        self._update_phase_step(
            phase_id,
            "Test idea generation complete",
            items_total=len(exploration_ids),
            items_completed=len(exploration_ids),
        )

        if config.reactive_mode and all_ideas:
            idea_preview = [
                {
                    "title": idea.title,
                    "priority": idea.priority,
                    "readiness": idea.spec_readiness,
                }
                for idea in all_ideas[:20]
            ]
            await self._ask_question_and_wait(
                phase_name="test_ideas",
                question_type="review_test_ideas",
                question_text=(
                    f"Generated {len(all_ideas)} test ideas. "
                    f"Priority breakdown: "
                    f"{sum(1 for i in all_ideas if i.priority == 'critical')} critical, "
                    f"{sum(1 for i in all_ideas if i.priority == 'high')} high, "
                    f"{sum(1 for i in all_ideas if i.priority == 'medium')} medium, "
                    f"{sum(1 for i in all_ideas if i.priority == 'low')} low. "
                    f"Proceed with spec generation?"
                ),
                context={"total": len(all_ideas), "test_ideas_preview": idea_preview},
                suggested_answers=[
                    "Proceed with all ready ideas",
                    "Focus on critical and high only",
                    "Skip ideas that need test data",
                ],
                default_answer="Proceed with all ready ideas",
            )

        return {
            "status": "completed",
            "total_test_ideas": len(all_ideas),
            "spec_tasks_created": self._count_spec_tasks(),
            "requirements_considered": len(requirements),
            "expected_min_spec_tasks": expected_spec_tasks,
        }

    # ------------------------------------------------------------------
    # Phase 4: Spec Generation
    # ------------------------------------------------------------------

    async def _run_spec_generation_phase(
        self, config: AutoPilotConfig, phase_id: int
    ) -> dict[str, Any]:
        """Generate test spec markdown files from requirements, one at a time."""
        candidate_tasks = self._load_open_spec_tasks()

        if not candidate_tasks:
            logger.warning(
                "No spec tasks to generate; creating fallback tasks from exploration evidence"
            )
            self._create_fallback_spec_tasks_from_exploration(config)
            candidate_tasks = self._load_open_spec_tasks()

        if not candidate_tasks:
            logger.warning(
                "Fallback spec task creation produced no tasks; creating entry-page smoke task"
            )
            self._create_entry_page_spec_task(config)
            candidate_tasks = self._load_open_spec_tasks()

        threshold = self._effective_priority_threshold(config)
        threshold_level = PRIORITY_ORDER.get(threshold, 3)
        eligible_tasks = [
            t
            for t in candidate_tasks
            if PRIORITY_ORDER.get(t.priority, 3) <= threshold_level
        ]
        filtered_tasks = [
            t
            for t in candidate_tasks
            if PRIORITY_ORDER.get(t.priority, 3) > threshold_level
        ]
        eligible_tasks.sort(key=lambda t: PRIORITY_ORDER.get(t.priority, 3))
        tasks = eligible_tasks[: config.max_specs]
        skipped_due_to_limit = eligible_tasks[config.max_specs :]

        batch_specs_generated = 0
        specs_dir = Path("specs") / "autopilot" / self.session_id
        specs_dir.mkdir(parents=True, exist_ok=True)

        for idx, task in enumerate(tasks):
            if self._cancelled.is_set():
                break

            self._update_phase_step(
                phase_id,
                f"Generating spec {idx + 1}/{len(tasks)}: {task.requirement_title or 'unnamed'}",
                items_total=len(tasks),
                items_completed=idx,
            )

            try:
                spec_path = self._generate_spec_from_task(task, specs_dir, config)
                if spec_path:
                    self._update_spec_task(
                        task.id, "completed", spec_path=str(spec_path)
                    )
                    batch_specs_generated += 1
                else:
                    self._update_spec_task(
                        task.id, "failed", error="Spec generation returned empty"
                    )
            except Exception as e:
                logger.warning(f"Spec generation failed for task {task.id}: {e}")
                self._update_spec_task(task.id, "failed", error=str(e)[:500])

        self._update_phase_step(
            phase_id,
            "Spec generation complete",
            items_total=len(tasks),
            items_completed=len(tasks),
        )

        if filtered_tasks:
            self._skip_spec_tasks(
                [task.id for task in filtered_tasks if task.id is not None],
                f"Skipped by priority threshold '{threshold}'",
            )
        if skipped_due_to_limit:
            self._skip_spec_tasks(
                [task.id for task in skipped_due_to_limit if task.id is not None],
                f"Skipped by max_specs limit ({config.max_specs})",
            )

        remaining_pending = self._count_pending_spec_tasks()
        completed_specs_total = self._count_completed_spec_tasks()
        failed_selected = len(tasks) - batch_specs_generated
        partial_success = failed_selected > 0 and completed_specs_total > 0
        self._update_session_field("total_specs_generated", completed_specs_total)

        if completed_specs_total == 0:
            raise RuntimeError("Spec generation produced 0 specs")

        return {
            "status": "completed",
            "specs_generated": completed_specs_total,
            "batch_specs_generated": batch_specs_generated,
            "total_tasks": len(tasks),
            "failed_selected_tasks": failed_selected,
            "partial_success": partial_success,
            "warning": (
                f"Generated {batch_specs_generated}/{len(tasks)} selected specs; continuing with completed specs"
                if partial_success
                else None
            ),
            "eligible_tasks": len(eligible_tasks),
            "filtered_by_priority": len(filtered_tasks),
            "skipped_due_to_max_specs": len(skipped_due_to_limit),
            "remaining_pending_tasks": remaining_pending,
            "priority_threshold": threshold,
        }

    # ------------------------------------------------------------------
    # Phase 5: Test Generation
    # ------------------------------------------------------------------

    async def _run_test_generation_phase(
        self, config: AutoPilotConfig, phase_id: int
    ) -> dict[str, Any]:
        """Generate and validate test code in parallel."""
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSpecTask
        from orchestrator.services.browser_pool import OperationType, get_browser_pool
        from orchestrator.services.load_test_lock import check_system_available
        from orchestrator.workflows.full_native_pipeline import FullNativePipeline

        # Load completed spec tasks
        with Session(engine) as db:
            stmt = (
                select(AutoPilotSpecTask)
                .where(AutoPilotSpecTask.session_id == self.session_id)
                .where(AutoPilotSpecTask.status == "completed")
                .where(AutoPilotSpecTask.spec_path.isnot(None))
            )
            spec_tasks = db.exec(stmt).all()

        if not spec_tasks:
            logger.warning("No completed spec tasks for test generation")
            raise RuntimeError("No completed specs are available for test generation")

        # Create test tasks for spec tasks that do not already have one
        test_tasks = self._create_test_tasks(spec_tasks)
        total = len(test_tasks)

        semaphore = asyncio.Semaphore(config.parallel_generation)
        results: dict[int, dict] = {}

        passed_count = 0
        failed_count = 0

        async def _generate_one(
            test_task_id: int, spec_path: str, spec_name: str, run_id: str
        ):
            nonlocal passed_count, failed_count

            async with semaphore:
                if self._cancelled.is_set():
                    return
                await self._wait_if_paused()

                # Block if a load test is running
                await check_system_available("autopilot_test_generation")
                await self._wait_if_paused()

                pool = await get_browser_pool()
                request_id = f"autopilot_test_{test_task_id}_{uuid.uuid4().hex[:6]}"

                async with pool.browser_slot(
                    request_id=request_id,
                    operation_type=OperationType.AUTOPILOT,
                    description=f"AutoPilot test: {spec_name}",
                ) as acquired:
                    if not acquired:
                        self._update_test_task(
                            test_task_id,
                            "error",
                            error_summary="Timeout waiting for browser slot",
                        )
                        failed_count += 1
                        return
                    await self._wait_if_paused()

                    generation_mode = (
                        "conservative_smoke"
                        if self._should_use_conservative_test_generation(spec_path)
                        else "native_e2e"
                    )
                    self._update_test_task(
                        test_task_id,
                        "running",
                        current_stage=generation_mode,
                    )
                    self._update_live_browser_state(
                        {
                            "active": True,
                            "phase": "test_generation",
                            "activity_label": f"Generating test for {spec_name}",
                            "status": "running",
                            "message": f"Running {generation_mode}",
                            "test_task_id": test_task_id,
                            "run_id": run_id,
                            "spec_name": spec_name,
                            "current_stage": generation_mode,
                            "agent_task_id": None,
                            "last_tool": "",
                            "last_tool_label": "",
                            "tool_calls": 0,
                            "browser_tool_calls": 0,
                            "interactions": 0,
                            "recent_tools": [],
                        }
                    )

                    # Create run directory
                    run_dir = Path("runs") / run_id
                    run_dir.mkdir(parents=True, exist_ok=True)

                    def on_task_enqueued(task_id: str) -> None:
                        self._update_live_browser_state(
                            {
                                "active": True,
                                "phase": "test_generation",
                                "activity_label": f"Generating test for {spec_name}",
                                "test_task_id": test_task_id,
                                "run_id": run_id,
                                "spec_name": spec_name,
                                "current_stage": generation_mode,
                                "agent_task_id": task_id,
                                "status": "queued",
                                "message": "Agent task queued for worker",
                            }
                        )

                    def on_tool_use(tool_name: str, tool_input: dict[str, Any]) -> None:
                        self._record_live_tool_use(
                            tool_name,
                            {
                                "active": True,
                                "phase": "test_generation",
                                "activity_label": f"Generating test for {spec_name}",
                                "test_task_id": test_task_id,
                                "run_id": run_id,
                                "spec_name": spec_name,
                                "current_stage": generation_mode,
                                "status": "tool_use",
                                "message": f"Using {self._short_tool_name(tool_name)}",
                                "last_tool_input": tool_input,
                            },
                        )

                    def on_progress(progress: dict[str, Any]) -> None:
                        last_tool = str(progress.get("last_tool") or "")
                        patch = {
                            **progress,
                            "active": True,
                            "phase": "test_generation",
                            "activity_label": f"Generating test for {spec_name}",
                            "test_task_id": test_task_id,
                            "run_id": run_id,
                            "spec_name": spec_name,
                            "current_stage": progress.get("current_stage") or generation_mode,
                            "status": progress.get("phase") or "running",
                            "message": (
                                f"Using {self._short_tool_name(last_tool)}"
                                if last_tool
                                else "Agent is running"
                            ),
                        }
                        if last_tool:
                            self._record_live_tool_use(last_tool, patch)
                        else:
                            self._update_live_browser_state(patch)

                    pipeline = FullNativePipeline(
                        project_id=config.project_id,
                        on_task_enqueued=on_task_enqueued,
                        on_progress=on_progress,
                        on_tool_use=on_tool_use,
                        owner_type="autopilot",
                        owner_id=self.session_id,
                        owner_label=f"AutoPilot {self.session_id}",
                    )
                    try:
                        if generation_mode == "conservative_smoke":
                            result = self._run_conservative_test_generation(
                                pipeline=pipeline,
                                spec_path=spec_path,
                                run_dir=run_dir,
                                browser="chromium",
                            )
                        else:
                            result = await pipeline.run(
                                spec_path=spec_path,
                                run_dir=run_dir,
                                browser="chromium",
                                hybrid_healing=config.hybrid_healing,
                            )

                        success = result.get("success", False)
                        test_path = result.get("test_path")
                        result_stage = result.get("stage") or generation_mode
                        healing_attempt = int(result.get("attempts") or 0)

                        if success:
                            self._update_test_task(
                                test_task_id,
                                "passed",
                                passed=True,
                                test_path=test_path,
                                current_stage=result_stage,
                                healing_attempt=healing_attempt,
                            )
                            passed_count += 1
                        else:
                            error_message = self._extract_task_error_summary(
                                run_dir, result
                            )
                            self._update_test_task(
                                test_task_id,
                                "failed",
                                passed=False,
                                test_path=test_path,
                                current_stage=result_stage,
                                error_summary=error_message,
                                healing_attempt=healing_attempt,
                            )
                            failed_count += 1

                        results[test_task_id] = result

                    except asyncio.CancelledError:
                        logger.info(
                            f"Auto Pilot test task {test_task_id} paused/cancelled"
                        )
                        raise
                    except Exception as e:
                        logger.error(
                            f"Test generation failed for {spec_name}: {e}",
                            exc_info=True,
                        )
                        self._update_test_task(
                            test_task_id,
                            "error",
                            current_stage="exception",
                            error_summary=str(e)[:500],
                        )
                        failed_count += 1

                # Update phase progress
                completed_so_far = passed_count + failed_count
                self._update_phase_step(
                    phase_id,
                    f"Generated {completed_so_far}/{total} tests ({passed_count} passed, {failed_count} failed)",
                    items_total=total,
                    items_completed=completed_so_far,
                )

        # Launch all test generations concurrently (bounded by semaphore + pool)
        for tt_id, spec_path, spec_name, run_id in test_tasks:
            t = asyncio.create_task(_generate_one(tt_id, spec_path, spec_name, run_id))
            self._test_tasks[tt_id] = t

        await asyncio.gather(*self._test_tasks.values(), return_exceptions=True)
        self._test_tasks.clear()  # Clean up references

        task_counts = self._count_test_task_statuses()
        total_generated = (
            task_counts["passed"] + task_counts["failed"] + task_counts["error"]
        )
        passed_count = task_counts["passed"]
        failed_count = task_counts["failed"] + task_counts["error"]

        self._update_session_field("total_tests_generated", total_generated)
        self._update_session_field("total_tests_passed", passed_count)
        self._update_session_field("total_tests_failed", failed_count)

        self._update_phase_step(
            phase_id,
            "Test generation complete",
            items_total=total,
            items_completed=total,
        )

        return {
            "status": "completed",
            "total": total_generated,
            "passed": passed_count,
            "failed": failed_count,
        }

    def _should_use_conservative_test_generation(
        self, spec_path: str | None = None
    ) -> bool:
        """Use deterministic smoke tests only when exploration evidence is weak."""
        config = self._get_session_config()
        exploration_quality = config.get("ai_quality", {}).get("exploration", {})
        weak_evidence = bool(exploration_quality.get("degraded_mode"))
        if not weak_evidence:
            return False
        if not spec_path:
            return True
        return not self._spec_has_actionable_e2e_steps(spec_path)

    def _spec_has_actionable_e2e_steps(self, spec_path: str) -> bool:
        """Return True when a spec asks for more than a page-load smoke check."""
        try:
            content = Path(spec_path).read_text()
        except Exception:
            return False

        steps_section = self._extract_markdown_section(content, "Steps").lower()
        if not steps_section.strip():
            return False

        actionable_terms = [
            "click",
            "fill",
            "enter",
            "submit",
            "select",
            "search",
            "filter",
            "login",
            "authenticated",
            "unauthenticated",
            "redirect",
            "navigate sequentially",
            "after each navigation",
            "keyboard",
            "focus",
            "viewport",
            "console",
            "accessibility",
            "snapshot",
        ]
        if any(term in steps_section for term in actionable_terms):
            return True

        numbered_steps = [
            line.strip()
            for line in steps_section.splitlines()
            if re.match(r"^\d+\.\s+", line.strip())
        ]
        smoke_terms = (
            "navigate to ",
            "wait for the page",
            "verify the response status",
            "verify the page renders",
            "verify page renders",
            "verify the page is reachable",
            "verify the page renders without",
        )
        non_smoke_steps = [
            step
            for step in numbered_steps
            if not any(term in step for term in smoke_terms)
        ]
        return bool(non_smoke_steps)

    def _extract_markdown_section(self, content: str, heading: str) -> str:
        pattern = rf"^##\s+{re.escape(heading)}\s*$"
        lines = content.splitlines()
        start = None
        for idx, line in enumerate(lines):
            if re.match(pattern, line.strip(), flags=re.IGNORECASE):
                start = idx + 1
                break
        if start is None:
            return ""
        end = len(lines)
        for idx in range(start, len(lines)):
            if lines[idx].startswith("## "):
                end = idx
                break
        return "\n".join(lines[start:end])

    def _run_conservative_test_generation(
        self, pipeline, spec_path: str, run_dir: Path, browser: str
    ) -> dict[str, Any]:
        """Generate and run a deterministic reachability test for weak/fallback evidence."""
        spec_file = Path(spec_path)
        spec_content = spec_file.read_text()
        target_url = self._extract_first_url(spec_content)
        if not target_url:
            return {
                "success": False,
                "error": "No target URL found in spec",
                "stage": "conservative_generation",
            }

        title = self._extract_spec_title(spec_content, spec_file.stem)
        tests_dir = Path("tests") / "generated"
        tests_dir.mkdir(parents=True, exist_ok=True)
        output_stem = self._sanitize_test_filename(
            f"{self.session_id}-{spec_file.stem}"
        )
        test_path = tests_dir / f"{output_stem}.spec.ts"
        test_path.write_text(
            self._render_conservative_playwright_test(title, target_url)
        )

        export_data = {
            "testFilePath": str(test_path),
            "code": test_path.read_text(),
            "dependencies": ["@playwright/test"],
            "notes": ["Generated deterministically for fallback Auto Pilot evidence"],
        }
        (run_dir / "export.json").write_text(json.dumps(export_data, indent=2))

        result = pipeline._run_test(str(test_path), str(run_dir), browser)
        if result.passed:
            (run_dir / "status.txt").write_text("passed")
            return {
                "success": True,
                "test_path": str(test_path),
                "attempts": 0,
                "stage": "conservative_completed",
            }

        (run_dir / "status.txt").write_text("failed")
        return {
            "success": False,
            "test_path": str(test_path),
            "error": result.error_summary or result.output[:500],
            "attempts": 0,
            "stage": "conservative_failed",
        }

    def _extract_task_error_summary(self, run_dir: Path, result: dict[str, Any]) -> str:
        """Prefer persisted pipeline diagnostics over a generic failure string."""
        pipeline_error = run_dir / "pipeline_error.json"
        if pipeline_error.exists():
            try:
                data = json.loads(pipeline_error.read_text())
                error = data.get("error") or data.get("error_tail")
                stage = data.get("stage")
                if error and stage:
                    return f"{stage}: {error}"[:1000]
                if error:
                    return str(error)[:1000]
            except Exception as exc:
                logger.debug(f"Unable to read pipeline error for {run_dir}: {exc}")

        validation = run_dir / "validation.json"
        if validation.exists():
            try:
                data = json.loads(validation.read_text())
                message = data.get("message") or data.get("error") or data.get("status")
                if message:
                    return str(message)[:1000]
            except Exception as exc:
                logger.debug(f"Unable to read validation error for {run_dir}: {exc}")

        return str(result.get("error") or "Test failed")[:1000]

    def _extract_first_url(self, text: str) -> str | None:
        match = re.search(r"https?://[^\s<>)\]}\"']+", text)
        return match.group(0).rstrip(".,;:") if match else None

    def _extract_spec_title(self, spec_content: str, fallback: str) -> str:
        for line in spec_content.splitlines():
            if line.startswith("# Test:"):
                return line.replace("# Test:", "", 1).strip() or fallback
        return fallback.replace("-", " ").title()

    def _sanitize_test_filename(self, value: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
        return safe[:120] or "autopilot-test"

    def _render_conservative_playwright_test(self, title: str, target_url: str) -> str:
        suite = json.dumps(title)
        url = json.dumps(target_url)
        return f"""import {{ test, expect }} from '@playwright/test';

test.describe({suite}, () => {{
  test('page is reachable and renders content', async ({{ page }}) => {{
    const response = await page.goto({url}, {{ waitUntil: 'domcontentloaded', timeout: 60000 }});

    expect(response, 'navigation response should exist').not.toBeNull();
    expect(response!.status(), 'page should not return a server error').toBeLessThan(500);
    await expect(page.locator('body')).toBeVisible();

    const bodyText = (await page.locator('body').innerText()).trim();
    expect(bodyText.length, 'page should render visible text').toBeGreaterThan(0);
  }});
}});
"""

    # ------------------------------------------------------------------
    # Phase 6: Reporting
    # ------------------------------------------------------------------

    async def _run_reporting_phase(
        self, config: AutoPilotConfig, phase_id: int
    ) -> dict[str, Any]:
        """Generate RTM and coverage report."""
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSpecTask
        from orchestrator.workflows.rtm_generator import RtmGenerator

        self._update_phase_step(phase_id, "Generating RTM...")

        # Collect spec paths that were successfully generated
        with Session(engine) as db:
            stmt = (
                select(AutoPilotSpecTask)
                .where(AutoPilotSpecTask.session_id == self.session_id)
                .where(AutoPilotSpecTask.status == "completed")
                .where(AutoPilotSpecTask.spec_path.isnot(None))
            )
            spec_tasks = db.exec(stmt).all()

        spec_paths = [t.spec_path for t in spec_tasks if t.spec_path]

        coverage_pct = 0.0
        rtm_mappings = 0

        if spec_paths:
            try:
                rtm_gen = RtmGenerator(project_id=config.project_id)
                rtm_result = await rtm_gen.generate_rtm(
                    specs_paths=spec_paths,
                    use_ai_matching=bool(
                        os.environ.get("ANTHROPIC_AUTH_TOKEN")
                        or os.environ.get("ANTHROPIC_API_KEY")
                        or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
                    ),
                )
                coverage_pct = rtm_result.coverage_percentage
                rtm_mappings = len(rtm_result.mappings)

                logger.info(
                    f"RTM generated: {coverage_pct:.1f}% coverage, {rtm_mappings} mappings"
                )
            except Exception as e:
                logger.warning(f"RTM generation failed: {e}")
        else:
            logger.warning("No spec paths available for RTM generation")

        self._update_session_field("coverage_percentage", coverage_pct)

        self._update_phase_step(
            phase_id,
            "Reporting complete",
            items_total=1,
            items_completed=1,
        )

        return {
            "status": "completed",
            "coverage_percentage": coverage_pct,
            "rtm_mappings": rtm_mappings,
            "specs_analyzed": len(spec_paths),
        }

    # ------------------------------------------------------------------
    # Question System
    # ------------------------------------------------------------------

    async def _ask_question_and_wait(
        self,
        phase_name: str,
        question_type: str,
        question_text: str,
        context: dict,
        suggested_answers: list[str],
        default_answer: str,
    ) -> str:
        """Pause pipeline, create question, wait for answer or timeout."""
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotQuestion

        question = AutoPilotQuestion(
            session_id=self.session_id,
            phase_name=phase_name,
            question_type=question_type,
            question_text=question_text,
            context_json=json.dumps(context, default=str),
            suggested_answers_json=json.dumps(suggested_answers),
            default_answer=default_answer,
            auto_continue_at=datetime.utcnow()
            + timedelta(hours=self._config.auto_continue_hours),
        )

        with Session(engine) as db:
            db.add(question)
            db.commit()
            db.refresh(question)
            self._current_question_id = question.id

        logger.info(f"Question asked (id={question.id}): {question_text[:100]}...")
        self._update_session_status("awaiting_input")

        # Wait for answer (or auto-continue timeout)
        self._question_answered.clear()
        try:
            await asyncio.wait_for(
                self._question_answered.wait(),
                timeout=self._config.auto_continue_hours * 3600,
            )
        except asyncio.TimeoutError:
            self._auto_continue_question(question.id, default_answer)

        resolved_answer = default_answer
        with Session(engine) as db:
            resolved = db.get(AutoPilotQuestion, question.id)
            if resolved and resolved.answer_text:
                resolved_answer = resolved.answer_text

        self._checkpoint_answers[question_type] = resolved_answer
        self._current_question_id = None
        self._update_session_status("running")
        return resolved_answer

    def _auto_continue_question(self, question_id: int, default_answer: str):
        """Mark a question as auto-continued with the default answer."""
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotQuestion

        with Session(engine) as db:
            question = db.get(AutoPilotQuestion, question_id)
            if question and question.status == "pending":
                question.status = "auto_continued"
                question.answer_text = default_answer
                question.answered_at = datetime.utcnow()
                db.add(question)
                db.commit()

        logger.info(
            f"Question {question_id} auto-continued with default: {default_answer}"
        )

    # ------------------------------------------------------------------
    # Pause / cancel helpers
    # ------------------------------------------------------------------

    async def _wait_if_paused(self):
        """Block until the pipeline is unpaused or cancelled."""
        if not self._paused.is_set():
            self._update_session_status("paused")
            logger.info("Pipeline paused, waiting for resume...")
            await self._paused.wait()
            if not self._cancelled.is_set():
                self._update_session_status("running")

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _update_session_status(self, status: str, error: str = None):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSession

        with Session(engine) as db:
            session = db.get(AutoPilotSession, self.session_id)
            if session:
                session.status = status
                if error:
                    session.error_message = error
                db.add(session)
                db.commit()

    def _update_session_field(self, field_name: str, value: Any):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSession

        with Session(engine) as db:
            session = db.get(AutoPilotSession, self.session_id)
            if session:
                setattr(session, field_name, value)
                db.add(session)
                db.commit()

    def _update_session_list(self, field_name: str, values: list[str]):
        """Update a JSON list field on the session (e.g. exploration_session_ids)."""
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSession

        with Session(engine) as db:
            session = db.get(AutoPilotSession, self.session_id)
            if session:
                setattr(session, field_name, values)
                db.add(session)
                db.commit()

    def _merge_session_config(self, patch: dict[str, Any]):
        """Merge diagnostic data into AutoPilotSession.config_json."""
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSession

        def deep_merge(
            base: dict[str, Any], incoming: dict[str, Any]
        ) -> dict[str, Any]:
            for key, value in incoming.items():
                if isinstance(value, dict) and isinstance(base.get(key), dict):
                    base[key] = deep_merge(base[key], value)
                else:
                    base[key] = value
            return base

        with Session(engine) as db:
            session = db.get(AutoPilotSession, self.session_id)
            if session:
                session.config = deep_merge(session.config or {}, patch)
                db.add(session)
                db.commit()

    def _update_live_browser_state(self, patch: dict[str, Any]) -> None:
        """Persist ephemeral browser/agent progress for the AutoPilot UI."""
        live_patch = {**patch, "updated_at": datetime.utcnow().isoformat()}
        self._merge_session_config({"live_browser": live_patch})

    def _record_live_tool_use(
        self, tool_name: str, patch: dict[str, Any] | None = None
    ) -> None:
        """Append a tool event to live browser state and persist the latest patch."""
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSession

        patch = patch or {}
        label = self._short_tool_name(tool_name)
        with Session(engine) as db:
            session = db.get(AutoPilotSession, self.session_id)
            if not session:
                return

            config = session.config or {}
            live = dict(config.get("live_browser") or {})
            recent_tools = list(live.get("recent_tools") or [])
            if not recent_tools or recent_tools[-1].get("name") != tool_name:
                recent_tools.append(
                    {
                        "name": tool_name,
                        "label": label,
                        "at": datetime.utcnow().isoformat(),
                    }
                )
                recent_tools = recent_tools[-12:]

            live.update(patch)
            live.update(
                {
                    "last_tool": tool_name,
                    "last_tool_label": label,
                    "recent_tools": recent_tools,
                    "updated_at": datetime.utcnow().isoformat(),
                }
            )
            config["live_browser"] = live
            session.config = config
            db.add(session)
            db.commit()

    @staticmethod
    def _short_tool_name(tool_name: str) -> str:
        if not tool_name:
            return ""
        if "__" in tool_name:
            return tool_name.rsplit("__", 1)[-1].replace("_", " ")
        return tool_name.replace("_", " ")

    def _update_overall_progress(self, progress: float):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSession

        with Session(engine) as db:
            session = db.get(AutoPilotSession, self.session_id)
            if session:
                session.overall_progress = min(progress, 1.0)
                db.add(session)
                db.commit()

    def _get_completed_phases(self) -> list[str]:
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSession

        with Session(engine) as db:
            session = db.get(AutoPilotSession, self.session_id)
            if session:
                completed = session.phases_completed
                valid = [
                    phase
                    for phase in completed
                    if self._completed_phase_still_valid(phase)
                ]
                if valid != completed:
                    session.phases_completed = valid
                    db.add(session)
                    db.commit()
                return valid
        return []

    def _phase_has_resumable_output(self, phase_name: str, result: dict) -> bool:
        """Guard phase completion against empty state that blocks downstream work."""
        status = result.get("status")
        if phase_name == "exploration":
            return bool(result.get("exploration_ids")) and (
                int(result.get("total_pages") or 0) > 0
                or int(result.get("total_flows") or 0) > 0
            )
        if phase_name == "test_ideas":
            expected = int(result.get("expected_min_spec_tasks") or 0)
            actual = self._count_spec_tasks()
            return actual >= expected if expected > 0 else actual > 0
        if phase_name == "spec_generation":
            return (
                int(result.get("specs_generated") or 0) > 0
                and int(result.get("remaining_pending_tasks") or 0) == 0
            )
        if status == "skipped" and phase_name in {"requirements", "test_generation"}:
            return False
        return True

    def _phase_output_error(self, phase_name: str, result: dict) -> str:
        if phase_name == "exploration":
            return "Exploration produced no persisted pages or sessions"
        if phase_name == "test_ideas":
            return "Test idea generation did not produce enough spec tasks for discovered unique requirements"
        if phase_name == "spec_generation":
            return "Spec generation produced 0 specs"
        return f"{phase_name.replace('_', ' ').title()} did not produce resumable output: {result.get('reason', 'empty output')}"

    def _completed_phase_still_valid(self, phase_name: str) -> bool:
        """Validate completed checkpoints before skipping them on resume."""
        if phase_name == "exploration":
            return bool(self._get_session_exploration_ids())
        if phase_name == "test_ideas":
            return self._has_spec_tasks()
        if phase_name == "spec_generation":
            return (
                self._count_completed_spec_tasks() > 0
                and self._count_pending_spec_tasks() == 0
            )
        if phase_name == "test_generation":
            return self._count_terminal_test_tasks() > 0
        return True

    def _add_completed_phase(self, phase_name: str):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSession

        with Session(engine) as db:
            session = db.get(AutoPilotSession, self.session_id)
            if session:
                completed = session.phases_completed
                if phase_name not in completed:
                    completed.append(phase_name)
                    session.phases_completed = completed
                    db.add(session)
                    db.commit()

    def _get_session_exploration_ids(self) -> list[str]:
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSession

        with Session(engine) as db:
            session = db.get(AutoPilotSession, self.session_id)
            if session:
                return session.exploration_session_ids
        return []

    def _get_session_config(self) -> dict[str, Any]:
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSession

        with Session(engine) as db:
            session = db.get(AutoPilotSession, self.session_id)
            if session:
                return session.config or {}
        return {}

    def _filter_exploration_ids_by_quality(
        self, exploration_ids: list[str]
    ) -> list[str]:
        """Return exploration IDs that are reliable enough for downstream generation."""
        config = self._get_session_config()
        by_session = (
            config.get("ai_quality", {}).get("exploration", {}).get("by_session", {})
        )
        if not by_session:
            return exploration_ids

        usable: list[str] = []
        gated: dict[str, str] = {}
        for exploration_id in exploration_ids:
            summary = by_session.get(exploration_id)
            if not summary:
                usable.append(exploration_id)
                continue
            gated_out, reason = should_gate_exploration(
                summary.get("quality"),
                summary.get("validation"),
                min_quality_score=50,
                allow_fallback=False,
            )
            if gated_out and self._is_legacy_category_validation_only(summary):
                logger.info(
                    "Allowing exploration %s through quality gate; validation failures are legacy category labels only",
                    exploration_id,
                )
                usable.append(exploration_id)
                continue
            if gated_out:
                gated[exploration_id] = reason or "quality_gate"
            else:
                usable.append(exploration_id)

        self._merge_session_config({"ai_quality": {"gated_explorations": gated}})
        return usable

    def _is_legacy_category_validation_only(self, summary: dict[str, Any]) -> bool:
        """Allow old runs where validation failed only on now-accepted flow categories."""
        validation = summary.get("validation") or {}
        if validation.get("valid", True):
            return False

        invalid_records = validation.get("invalid_records") or []
        if not invalid_records:
            return False

        if not all(
            issue.get("record_type") == "flow"
            and str(issue.get("message", "")).startswith("invalid category ")
            for issue in invalid_records
        ):
            return False

        quality = summary.get("quality") or {}
        if quality.get("source_type") != SOURCE_OBSERVED:
            return False

        try:
            score = int(quality.get("quality_score", 0))
        except (TypeError, ValueError):
            score = 0
        return score >= 50

    # ------------------------------------------------------------------
    # Phase record helpers
    # ------------------------------------------------------------------

    def _create_phase_record(self, phase_name: str) -> int:
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotPhase

        phase_order = next(
            (i for i, (name, _) in enumerate(self.PHASES) if name == phase_name),
            0,
        )

        with Session(engine) as db:
            # Check for existing record (resume case)
            stmt = (
                select(AutoPilotPhase)
                .where(AutoPilotPhase.session_id == self.session_id)
                .where(AutoPilotPhase.phase_name == phase_name)
            )
            existing = db.exec(stmt).first()
            if existing:
                existing.status = "running"
                existing.started_at = datetime.utcnow()
                existing.completed_at = None
                existing.error_message = None
                existing.progress = 0.0
                db.add(existing)
                db.commit()
                db.refresh(existing)
                return existing.id

            phase = AutoPilotPhase(
                session_id=self.session_id,
                phase_name=phase_name,
                phase_order=phase_order,
                status="running",
                started_at=datetime.utcnow(),
            )
            db.add(phase)
            db.commit()
            db.refresh(phase)
            return phase.id

    def _complete_phase_record(self, phase_id: int, result: dict):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotPhase

        with Session(engine) as db:
            phase = db.get(AutoPilotPhase, phase_id)
            if phase:
                phase.status = "completed"
                phase.progress = 1.0
                phase.completed_at = datetime.utcnow()
                phase.result_summary = result
                db.add(phase)
                db.commit()

    def _fail_phase_record(self, phase_id: int, error: str):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotPhase

        with Session(engine) as db:
            phase = db.get(AutoPilotPhase, phase_id)
            if phase:
                phase.status = "failed"
                phase.error_message = error[:1000]
                phase.completed_at = datetime.utcnow()
                db.add(phase)
                db.commit()

    def _update_phase_step(
        self,
        phase_id: int,
        step: str,
        items_total: int = 0,
        items_completed: int = 0,
    ):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotPhase, AutoPilotSession

        with Session(engine) as db:
            phase = db.get(AutoPilotPhase, phase_id)
            if phase:
                phase.current_step = step
                phase.items_total = items_total
                phase.items_completed = items_completed
                if items_total > 0:
                    phase.progress = items_completed / items_total
                db.add(phase)
                session = db.get(AutoPilotSession, self.session_id)
                if session:
                    session.current_phase_progress = phase.progress
                    db.add(session)
                db.commit()

    # ------------------------------------------------------------------
    # Exploration result storage
    # ------------------------------------------------------------------

    def _store_exploration_results(self, session_id: str, result, project_id: str):
        """Store exploration results in the exploration store, mirroring
        the pattern from orchestrator/api/exploration.py."""
        from orchestrator.memory.exploration_store import get_exploration_store
        from orchestrator.workflows.spec_scenario_builder import (
            render_scenario_markdown,
            sanitize_filename,
            scenario_from_requirement,
            scenario_from_test_idea,
        )

        store = get_exploration_store(project_id=project_id)

        # Create session record if it does not already exist
        existing = store.get_session(session_id)
        if not existing:
            store.create_session(
                session_id=session_id,
                entry_url=result.entry_url,
                strategy=self._config.strategy if self._config else "goal_directed",
                config={},
            )

        # Update status and counts
        validation_summary = validate_exploration_result(result)
        if not validation_summary.get("valid", True):
            logger.warning(
                "Exploration %s has invalid records before persistence: %s",
                session_id,
                validation_summary.get("invalid_records", []),
            )

        store.update_session_status(session_id, result.status, result.error_message)
        store.update_session_counts(
            session_id,
            pages=result.pages_discovered,
            flows=len(result.flows),
            elements=result.elements_discovered,
            api_endpoints=len(result.api_endpoints),
        )

        # Store transitions
        for t in result.transitions:
            valid, invalid_reason = is_valid_transition(t)
            if not valid:
                logger.warning(
                    f"Skipping invalid transition {t.sequence}: {invalid_reason}"
                )
                continue
            try:
                store.store_transition(
                    session_id=session_id,
                    sequence_number=t.sequence,
                    action_type=t.action_type,
                    action_target=t.action_element or {},
                    action_value=t.action_value,
                    before_url=t.before_url,
                    after_url=t.after_url,
                    transition_type=t.transition_type,
                    before_page_type=t.before_page_type,
                    after_page_type=t.after_page_type,
                    api_calls=t.api_calls,
                    changes_description=t.changes_description,
                )
            except Exception as te:
                logger.warning(f"Failed to store transition {t.sequence}: {te}")

        # Store flows
        stored_flows = 0
        for idx, flow in enumerate(result.flows, 1):
            valid, invalid_reason = is_valid_flow(flow)
            if not valid:
                logger.warning(f"Skipping invalid flow '{flow.name}': {invalid_reason}")
                continue
            try:
                normalized_steps = self._normalize_flow_steps(flow.steps)
                flow_name = self._normalize_flow_name(
                    flow.name, flow.category, flow.start_url, flow.end_url, idx
                )
                flow_category = self._normalize_flow_category(flow.category)
                store.store_flow(
                    session_id=session_id,
                    flow_name=flow_name,
                    flow_category=flow_category,
                    start_url=flow.start_url or result.entry_url,
                    end_url=flow.end_url or flow.start_url or result.entry_url,
                    step_count=len(normalized_steps),
                    is_success_path=flow.is_success_path,
                    description=flow.outcome,
                    preconditions=flow.preconditions,
                    postconditions=flow.postconditions,
                    steps=normalized_steps,
                )
                stored_flows += 1
            except Exception as fe:
                logger.warning(f"Failed to store flow '{flow.name}': {fe}")
        if result.flows and stored_flows == 0:
            logger.error(
                "Exploration produced %s flows but none were persisted for %s",
                len(result.flows),
                session_id,
            )

        # Store API endpoints
        for endpoint in result.api_endpoints:
            try:
                store.store_api_endpoint(
                    session_id=session_id,
                    method=endpoint.get("method", "GET"),
                    url=endpoint.get("url", ""),
                    response_status=endpoint.get("status"),
                    triggered_by_action=endpoint.get("triggered_by"),
                    request_headers=endpoint.get("request_headers"),
                    request_body_sample=endpoint.get("request_body"),
                    response_body_sample=endpoint.get("response_body"),
                )
            except Exception as ae:
                logger.warning(
                    f"Failed to store API endpoint {endpoint.get('url')}: {ae}"
                )

        # Store issues
        for issue in getattr(result, "issues", []) or []:
            valid, invalid_reason = is_valid_issue(issue)
            if not valid:
                logger.warning(
                    f"Skipping invalid issue '{issue.issue_type}': {invalid_reason}"
                )
                continue
            try:
                store.store_issue(
                    session_id=session_id,
                    issue_type=issue.issue_type,
                    severity=issue.severity,
                    url=issue.url,
                    description=issue.description,
                    element=issue.element,
                    evidence=issue.evidence,
                )
            except Exception as ie:
                logger.warning(f"Failed to store issue '{issue.issue_type}': {ie}")

    def _get_discovered_flow_names(
        self, exploration_ids: list[str], project_id: str
    ) -> list[str]:
        """Get flow names from completed explorations."""
        from orchestrator.memory.exploration_store import get_exploration_store

        store = get_exploration_store(project_id=project_id)
        names = []
        for eid in exploration_ids:
            flows = store.get_session_flows(eid)
            if flows:
                for idx, f in enumerate(flows, 1):
                    names.append(
                        self._normalize_flow_name(
                            f.flow_name, f.flow_category, f.start_url, f.end_url, idx
                        )
                    )
                continue

            for idx, flow in enumerate(self._load_flow_artifacts(eid), 1):
                names.append(
                    self._normalize_flow_name(
                        flow.get("name") or flow.get("title"),
                        flow.get("category"),
                        flow.get("startUrl")
                        or flow.get("start_url")
                        or flow.get("entry_point"),
                        flow.get("endUrl")
                        or flow.get("end_url")
                        or flow.get("exit_point"),
                        idx,
                    )
                )
        return names

    def _normalize_flow_steps(self, raw_steps: Any) -> list[dict[str, Any]]:
        """Normalize agent-emitted flow steps before DB persistence."""
        steps: list[dict[str, Any]] = []
        if not isinstance(raw_steps, list):
            return steps

        for step in raw_steps:
            if isinstance(step, dict):
                action = (
                    step.get("action")
                    or step.get("actionType")
                    or step.get("action_type")
                    or step.get("type")
                    or "step"
                )
                element = (
                    step.get("element")
                    or step.get("elementName")
                    or step.get("element_name")
                    or step.get("description")
                    or step.get("actionDescription")
                    or step.get("action_description")
                    or action
                )
                steps.append(
                    {
                        "action": str(action),
                        "element": str(element),
                        "ref": step.get("ref")
                        or step.get("elementRef")
                        or step.get("element_ref"),
                        "role": step.get("role")
                        or step.get("elementRole")
                        or step.get("element_role"),
                        "value": step.get("value"),
                    }
                )
            elif step is not None:
                steps.append({"action": "step", "element": str(step)})

        return steps

    def _normalize_flow_category(self, category: Any) -> str:
        value = str(category or "navigation").strip().lower()
        value = re.sub(r"[^a-z0-9_]+", "_", value).strip("_")
        return value or "navigation"

    def _normalize_flow_name(
        self,
        name: Any,
        category: Any,
        start_url: Any,
        end_url: Any,
        index: int,
    ) -> str:
        raw = str(name or "").strip()
        if re.search(r"[A-Za-z0-9]", raw):
            return raw[:160]

        url = str(end_url or start_url or "").strip()
        path = urlparse(url).path.strip("/") if url else ""
        label = path.replace("/", " / ") if path else "application"
        category_label = (
            self._normalize_flow_category(category).replace("_", " ").title()
        )
        return f"{category_label} Flow {index}: {label}"[:160]

    def _load_flow_artifacts(self, exploration_session_id: str) -> list[dict[str, Any]]:
        """Load flow artifacts when DB records are missing or from older sessions."""
        candidates = [
            Path("runs") / "explorations" / exploration_session_id / "flows.json",
            Path("runs") / exploration_session_id / "flows.json",
            Path("/app/runs/explorations") / exploration_session_id / "flows.json",
            Path("/app/runs") / exploration_session_id / "flows.json",
        ]
        for path in candidates:
            if not path.exists():
                continue
            try:
                raw = json.loads(path.read_text())
                data = raw.get("flows", raw) if isinstance(raw, dict) else raw
                return (
                    [item for item in data if isinstance(item, dict)]
                    if isinstance(data, list)
                    else []
                )
            except Exception as exc:
                logger.warning(f"Failed to load flow artifacts from {path}: {exc}")
                return []
        return []

    # ------------------------------------------------------------------
    # Spec task helpers
    # ------------------------------------------------------------------

    def _effective_priority_threshold(self, config: AutoPilotConfig) -> str:
        """Apply checkpoint focus answers on top of the configured threshold."""
        answer_text = " ".join(
            str(self._checkpoint_answers.get(key, "")).lower()
            for key in ("review_requirements", "review_test_ideas")
        )
        if "critical" in answer_text and "high" in answer_text:
            return "high"
        if "skip low" in answer_text:
            return "medium"
        return config.priority_threshold

    def _create_fallback_spec_tasks_from_exploration(
        self, config: AutoPilotConfig
    ) -> None:
        """Create deterministic spec tasks directly from exploration evidence."""
        from orchestrator.memory.exploration_store import get_exploration_store

        store = get_exploration_store(project_id=config.project_id)
        exploration_ids = self._get_session_exploration_ids()

        created = 0
        for eid in exploration_ids:
            flows = store.get_session_flows(eid)
            if flows:
                for flow in flows:
                    priority = (
                        "high"
                        if flow.flow_category
                        in {"authentication", "crud", "form_submission"}
                        else "medium"
                    )
                    if self._create_spec_task_if_missing(flow.flow_name, priority):
                        created += 1
                continue

            transitions = store.get_session_transitions(eid)
            for idx, transition in enumerate(transitions[:10], 1):
                title = f"Validate discovered {transition.action_type.replace('_', ' ')} path {idx}"
                if self._create_spec_task_if_missing(title, "medium"):
                    created += 1

        if created == 0:
            self._create_entry_page_spec_task(config)

    def _create_entry_page_spec_task(self, config: AutoPilotConfig) -> None:
        title = "Validate application entry page availability"
        self._create_spec_task_if_missing(title, "medium")

    def _get_requirements_for_explorations(
        self, project_id: str, exploration_ids: list[str]
    ):
        """Load requirements produced from this Auto Pilot run's explorations."""
        from orchestrator.memory.exploration_store import get_exploration_store

        store = get_exploration_store(project_id=project_id)
        exploration_id_set = set(exploration_ids)
        return [
            req
            for req in store.get_requirements()
            if req.source_session_id in exploration_id_set
        ]

    def _normalized_spec_task_key(self, title: str | None) -> str:
        """Normalize requirement and idea titles for duplicate avoidance."""
        key = re.sub(r"\s+", " ", (title or "").strip().lower())
        key = re.sub(r"^(validate|verify|test|check)\s+", "", key)
        return key

    def _count_unique_requirement_targets(self, requirements) -> int:
        """Count distinct requirement behaviors, not duplicate requirement rows."""
        return len(
            {
                self._normalized_spec_task_key(getattr(req, "title", None))
                for req in requirements
                if self._normalized_spec_task_key(getattr(req, "title", None))
            }
        )

    def _create_spec_task_if_missing(self, title: str, priority: str) -> bool:
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSpecTask

        normalized_title = (title or "Validate application behavior").strip()[:200]
        with Session(engine) as db:
            existing = db.exec(
                select(AutoPilotSpecTask)
                .where(AutoPilotSpecTask.session_id == self.session_id)
                .where(AutoPilotSpecTask.requirement_title == normalized_title)
            ).first()
            if existing:
                return False
            db.add(
                AutoPilotSpecTask(
                    session_id=self.session_id,
                    requirement_title=normalized_title,
                    priority=priority if priority in PRIORITY_ORDER else "medium",
                    status="pending",
                )
            )
            db.commit()
            return True

    def _create_spec_tasks_from_requirements(self, requirements) -> int:
        """Create AutoPilotSpecTask records for each requirement."""
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSpecTask

        created = 0
        with Session(engine) as db:
            existing_tasks = db.exec(
                select(AutoPilotSpecTask).where(
                    AutoPilotSpecTask.session_id == self.session_id
                )
            ).all()
            existing_requirement_ids = {
                task.requirement_id
                for task in existing_tasks
                if task.requirement_id is not None
            }
            existing_titles = {
                self._normalized_spec_task_key(task.requirement_title)
                for task in existing_tasks
            }
            for req in requirements:
                req_id = getattr(req, "id", None)
                key = self._normalized_spec_task_key(req.title)
                if (
                    req_id is not None and req_id in existing_requirement_ids
                ) or key in existing_titles:
                    continue
                task = AutoPilotSpecTask(
                    session_id=self.session_id,
                    requirement_id=req_id,
                    requirement_title=req.title,
                    priority=req.priority,
                    status="pending",
                )
                db.add(task)
                existing_titles.add(key)
                if req_id is not None:
                    existing_requirement_ids.add(req_id)
                created += 1
            db.commit()
        return created

    def _create_spec_tasks_from_test_ideas(self, test_ideas) -> int:
        """Create AutoPilotSpecTask records for generated test ideas."""
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSpecTask

        created = 0
        with Session(engine) as db:
            existing_tasks = db.exec(
                select(AutoPilotSpecTask).where(
                    AutoPilotSpecTask.session_id == self.session_id
                )
            ).all()
            existing_titles = {
                self._normalized_spec_task_key(task.requirement_title)
                for task in existing_tasks
            }
            for idea in test_ideas:
                requirement_id = self._lookup_requirement_id_for_test_idea(idea)
                key = self._normalized_spec_task_key(idea.title)
                if key in existing_titles:
                    continue
                task = AutoPilotSpecTask(
                    session_id=self.session_id,
                    requirement_id=requirement_id,
                    requirement_title=idea.title,
                    priority=idea.priority,
                    status="pending",
                )
                db.add(task)
                existing_titles.add(key)
                created += 1
            db.commit()
        return created

    def _has_spec_tasks(self) -> bool:
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSpecTask

        with Session(engine) as db:
            stmt = (
                select(AutoPilotSpecTask)
                .where(AutoPilotSpecTask.session_id == self.session_id)
                .limit(1)
            )
            return db.exec(stmt).first() is not None

    def _count_spec_tasks(self) -> int:
        from sqlalchemy import func

        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSpecTask

        with Session(engine) as db:
            stmt = (
                select(func.count())
                .select_from(AutoPilotSpecTask)
                .where(AutoPilotSpecTask.session_id == self.session_id)
            )
            return int(db.exec(stmt).one())

    def _count_completed_spec_tasks(self) -> int:
        from sqlalchemy import func

        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSpecTask

        with Session(engine) as db:
            stmt = (
                select(func.count())
                .select_from(AutoPilotSpecTask)
                .where(AutoPilotSpecTask.session_id == self.session_id)
                .where(AutoPilotSpecTask.status == "completed")
                .where(AutoPilotSpecTask.spec_path.isnot(None))
            )
            return int(db.exec(stmt).one())

    def _count_pending_spec_tasks(self) -> int:
        from sqlalchemy import func

        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSpecTask

        with Session(engine) as db:
            stmt = (
                select(func.count())
                .select_from(AutoPilotSpecTask)
                .where(AutoPilotSpecTask.session_id == self.session_id)
                .where(AutoPilotSpecTask.status == "pending")
            )
            return int(db.exec(stmt).one())

    def _load_open_spec_tasks(self):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSpecTask

        with Session(engine) as db:
            stmt = (
                select(AutoPilotSpecTask)
                .where(AutoPilotSpecTask.session_id == self.session_id)
                .where(AutoPilotSpecTask.status.in_(["pending", "failed"]))
            )
            return db.exec(stmt).all()

    def _count_terminal_test_tasks(self) -> int:
        from sqlalchemy import func

        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotTestTask

        with Session(engine) as db:
            stmt = (
                select(func.count())
                .select_from(AutoPilotTestTask)
                .where(AutoPilotTestTask.session_id == self.session_id)
                .where(
                    AutoPilotTestTask.status.in_(
                        ["passed", "failed", "error", "skipped"]
                    )
                )
            )
            return int(db.exec(stmt).one())

    def _count_test_task_statuses(self) -> dict[str, int]:
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotTestTask

        counts = {
            "passed": 0,
            "failed": 0,
            "error": 0,
            "skipped": 0,
            "pending": 0,
            "running": 0,
            "paused": 0,
        }
        with Session(engine) as db:
            stmt = select(AutoPilotTestTask).where(
                AutoPilotTestTask.session_id == self.session_id
            )
            for task in db.exec(stmt).all():
                status = task.status if task.status in counts else "error"
                counts[status] += 1
        return counts

    def _update_spec_task(
        self,
        task_id: int,
        status: str,
        spec_path: str = None,
        error: str = None,
    ):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSpecTask

        with Session(engine) as db:
            task = db.get(AutoPilotSpecTask, task_id)
            if task:
                task.status = status
                if spec_path:
                    task.spec_path = spec_path
                    task.spec_name = Path(spec_path).stem
                if error:
                    task.error_message = error[:1000]
                if status in ("completed", "failed"):
                    task.completed_at = datetime.utcnow()
                db.add(task)
                db.commit()

    def _skip_spec_tasks(self, task_ids: list[int], reason: str):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSpecTask

        if not task_ids:
            return

        with Session(engine) as db:
            stmt = (
                select(AutoPilotSpecTask)
                .where(AutoPilotSpecTask.id.in_(task_ids))
                .where(AutoPilotSpecTask.session_id == self.session_id)
                .where(AutoPilotSpecTask.status.in_(["pending", "failed"]))
            )
            for task in db.exec(stmt).all():
                task.status = "skipped"
                task.error_message = reason[:1000]
                task.completed_at = datetime.utcnow()
                db.add(task)
            db.commit()

    def _generate_spec_from_task(
        self,
        task,
        specs_dir: Path,
        config: AutoPilotConfig,
    ) -> Path | None:
        """Generate a markdown spec file from a spec task's requirement data.

        Builds a spec from the requirement title, acceptance criteria (looked up
        from the exploration store), and the exploration context.
        """
        from orchestrator.memory.exploration_store import get_exploration_store
        from orchestrator.workflows.spec_scenario_builder import (
            render_scenario_markdown,
            sanitize_filename,
            scenario_from_requirement,
            scenario_from_test_idea,
        )

        store = get_exploration_store(project_id=config.project_id)

        # Look up requirement details from the store
        requirements = store.get_requirements()
        req = None
        if getattr(task, "requirement_id", None):
            req = next((r for r in requirements if r.id == task.requirement_id), None)
        if not req and task.requirement_title:
            req = next(
                (r for r in requirements if r.title == task.requirement_title),
                None,
            )

        idea = (
            self._get_test_idea_for_task(task.requirement_title, config.project_id)
            if task.requirement_title
            else None
        )

        title = task.requirement_title or "Unnamed Test"
        safe_name = sanitize_filename(title)[:60]
        task_suffix = getattr(task, "id", None) or uuid.uuid4().hex[:8]
        spec_filename = f"{safe_name}-{task_suffix}.md"
        spec_path = specs_dir / spec_filename

        # Determine target URL from exploration sessions
        target_url = (
            config.entry_urls[0] if config.entry_urls else "https://example.com"
        )

        if idea:
            scenario = scenario_from_test_idea(
                idea, target_url=target_url, fallback_title=title
            )
        elif req:
            # Try to find matching flow for step details
            exploration_ids = self._get_session_exploration_ids()
            matching_flow = None
            for eid in exploration_ids:
                flows = store.get_session_flows(eid)
                for flow in flows:
                    # Simple name matching
                    if (
                        req.title.lower() in flow.flow_name.lower()
                        or flow.flow_name.lower() in req.title.lower()
                    ):
                        matching_flow = flow
                        break
                if matching_flow:
                    break

            flow_steps = []
            source_flows = []
            if matching_flow:
                target_url = matching_flow.start_url or target_url
                source_flows.append(matching_flow.flow_name)
                for fs in store.get_flow_steps(matching_flow.id):
                    if fs.value is not None:
                        flow_steps.append(
                            f'{fs.action_type.capitalize()} "{fs.value}" into the {fs.element_name or "field"}'
                        )
                    else:
                        flow_steps.append(
                            f"{fs.action_type.capitalize()} the {fs.element_name or 'element'}"
                        )

            scenario = scenario_from_requirement(
                title=req.title,
                description=req.description or f"Test for: {req.title}",
                target_url=target_url,
                acceptance_criteria=list(req.acceptance_criteria or []),
                flow_steps=flow_steps,
                priority=req.priority,
                category=req.category,
                source_flows=source_flows,
            )
        else:
            scenario = scenario_from_requirement(
                title=title,
                description=f"Automated test for: {title}",
                target_url=target_url,
                flow_steps=[f"Verify {title}"],
            )

        spec_path.write_text(render_scenario_markdown(scenario))
        has_richer_source = self._source_has_richer_e2e_evidence(
            idea,
            locals().get("flow_steps", []),
        )
        if has_richer_source and not self._spec_has_actionable_e2e_steps(
            str(spec_path)
        ):
            raise ValueError(
                f"Generated spec for '{title}' collapsed richer source evidence into a smoke check"
            )
        logger.info(f"Generated spec: {spec_path}")
        return spec_path

    def _source_has_richer_e2e_evidence(
        self, idea: dict[str, Any] | None, flow_steps: list[str] | None
    ) -> bool:
        """Return True when upstream evidence should produce a real E2E scenario."""
        if idea:
            combined = " ".join(
                str(item)
                for item in (
                    list(idea.get("suggested_steps") or [])
                    + list(idea.get("expected_outcomes") or [])
                    + list(idea.get("source_flows") or [])
                )
            ).lower()
            if any(
                term in combined
                for term in (
                    "click",
                    "fill",
                    "enter",
                    "submit",
                    "select",
                    "search",
                    "filter",
                    "login",
                    "redirect",
                    "keyboard",
                    "viewport",
                    "console",
                    "accessibility",
                )
            ):
                return True

        combined_steps = " ".join(flow_steps or []).lower()
        return any(
            term in combined_steps
            for term in (
                "click",
                "fill",
                "enter",
                "submit",
                "select",
                "search",
                "filter",
            )
        )

    def _get_test_idea_for_task(
        self, title: str, project_id: str
    ) -> dict[str, Any] | None:
        """Look up a generated test idea by exact title."""
        try:
            from orchestrator.memory.manager import get_memory_manager

            manager = get_memory_manager(project_id=project_id)
            for idea in manager.get_test_ideas(feature=title, max_results=10):
                if (idea.get("title") or "").strip().lower() == title.strip().lower():
                    return idea
        except Exception as exc:
            logger.debug(f"Unable to load generated test idea for '{title}': {exc}")
        return None

    def _lookup_requirement_id_for_test_idea(self, idea) -> int | None:
        """Resolve a generated test idea to its strongest upstream requirement."""
        if not getattr(idea, "source_requirements", None):
            return None
        try:
            from orchestrator.memory.exploration_store import get_exploration_store

            project_id = self._config.project_id if self._config else self.project_id
            store = get_exploration_store(project_id=project_id)
            requirements = store.get_requirements()
            source_keys = {
                str(item).strip().lower()
                for item in idea.source_requirements
                if str(item).strip()
            }
            for req in requirements:
                if (
                    req.req_code.lower() in source_keys
                    or req.title.strip().lower() in source_keys
                ):
                    return req.id
        except Exception as exc:
            logger.debug(
                f"Unable to resolve requirement for test idea '{getattr(idea, 'title', '')}': {exc}"
            )
        return None

    # ------------------------------------------------------------------
    # Test task helpers
    # ------------------------------------------------------------------

    def _create_test_tasks(self, spec_tasks) -> list[tuple]:
        """Create AutoPilotTestTask records and return (task_id, spec_path, spec_name) tuples."""
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotTestTask

        result_tuples = []

        with Session(engine) as db:
            for st in spec_tasks:
                # Check if a test task already exists for this spec task
                stmt = (
                    select(AutoPilotTestTask)
                    .where(AutoPilotTestTask.session_id == self.session_id)
                    .where(AutoPilotTestTask.spec_task_id == st.id)
                    .order_by(AutoPilotTestTask.id)
                )
                existing_tasks = db.exec(stmt).all()
                existing = existing_tasks[0] if existing_tasks else None

                for duplicate in existing_tasks[1:]:
                    if duplicate.status not in ("passed", "skipped"):
                        duplicate.status = "skipped"
                        duplicate.error_summary = (
                            "Duplicate test task superseded by canonical task"
                        )
                        duplicate.completed_at = datetime.utcnow()
                        db.add(duplicate)

                if existing and existing.status in ("passed",):
                    # Already passed, skip
                    continue

                if existing and existing.status in (
                    "pending",
                    "running",
                    "paused",
                    "failed",
                    "error",
                    "skipped",
                ):
                    # Re-attempt
                    existing.status = "pending"
                    existing.error_summary = None
                    existing.started_at = None
                    existing.completed_at = None
                    existing.passed = None
                    existing.run_id = existing.run_id or self._build_test_run_id(
                        existing.id or st.id, st.spec_name or st.spec_path
                    )
                    db.add(existing)
                    db.commit()
                    db.refresh(existing)
                    result_tuples.append(
                        (
                            existing.id,
                            st.spec_path,
                            st.spec_name or Path(st.spec_path).stem,
                            existing.run_id,
                        )
                    )
                    continue

                # Create new test task
                tt = AutoPilotTestTask(
                    session_id=self.session_id,
                    spec_task_id=st.id,
                    spec_name=st.spec_name
                    or (Path(st.spec_path).stem if st.spec_path else None),
                    spec_path=st.spec_path,
                    status="pending",
                )
                db.add(tt)
                db.commit()
                db.refresh(tt)
                tt.run_id = self._build_test_run_id(tt.id, tt.spec_name or st.spec_path)
                db.add(tt)
                db.commit()
                db.refresh(tt)
                result_tuples.append(
                    (tt.id, st.spec_path, tt.spec_name or "unknown", tt.run_id)
                )

        return result_tuples

    def _build_test_run_id(self, task_id: int | None, spec_name: str | None) -> str:
        safe_spec = self._sanitize_test_filename(spec_name or "test")
        return f"{self.session_id}-task-{task_id or 'new'}-{safe_spec}"[:160]

    def _ensure_test_run_record(self, db: Session, task) -> None:
        from orchestrator.api.models_db import TestRun

        if not task.run_id:
            return
        run = db.get(TestRun, task.run_id)
        if not run:
            run = TestRun(
                id=task.run_id,
                spec_name=task.spec_name
                or task.spec_path
                or f"autopilot-task-{task.id}",
                test_name=task.spec_name,
                status=task.status,
                project_id=self.project_id,
                browser="chromium",
                test_type="browser",
            )
        run.spec_name = task.spec_name or run.spec_name
        run.test_name = task.spec_name or run.test_name
        run.status = task.status
        run.current_stage = task.current_stage
        run.stage_message = task.error_summary or task.current_stage
        run.error_message = (
            task.error_summary if task.status in ("failed", "error") else None
        )
        run.healing_attempt = task.healing_attempt
        run.started_at = task.started_at or run.started_at
        if task.status in (
            "passed",
            "failed",
            "error",
            "paused",
            "cancelled",
            "skipped",
        ):
            run.completed_at = task.completed_at
        db.add(run)

    def _update_test_task(
        self,
        task_id: int,
        status: str,
        passed: bool = None,
        test_path: str = None,
        current_stage: str = None,
        error_summary: str = None,
        healing_attempt: int | None = None,
    ):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotTestTask

        with Session(engine) as db:
            task = db.get(AutoPilotTestTask, task_id)
            if task:
                if task.status == "paused" and status != "pending":
                    logger.info(
                        f"Skipping stale update for paused Auto Pilot test task {task_id}: {status}"
                    )
                    return
                task.status = status
                if passed is not None:
                    task.passed = passed
                if test_path:
                    task.test_path = test_path
                if current_stage:
                    task.current_stage = current_stage[:100]
                if error_summary:
                    task.error_summary = error_summary[:1000]
                if healing_attempt is not None:
                    task.healing_attempt = healing_attempt
                if status == "running":
                    task.started_at = datetime.utcnow()
                if status in ("passed", "failed", "error", "paused"):
                    task.completed_at = datetime.utcnow()
                db.add(task)
                self._ensure_test_run_record(db, task)
                db.commit()
