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
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlmodel import Session, select

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
            logger.warning(f"Test task {task_id} not found or already done in session {self.session_id}")

    def pause(self):
        """Pause the pipeline at the next checkpoint."""
        self._paused.clear()

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
                summary["phases"][phase_name] = {"status": "skipped (already completed)"}
                continue

            # Update current phase
            self._update_session_field("current_phase", phase_name)
            logger.info(f"{'=' * 60}")
            logger.info(f"AUTO PILOT - Phase: {phase_name}")
            logger.info(f"{'=' * 60}")

            # Create/update phase record
            phase_record_id = self._create_phase_record(phase_name)

            try:
                result = await runner(config, phase_record_id)
                summary["phases"][phase_name] = result

                # Mark phase completed
                self._complete_phase_record(phase_record_id, result)
                self._add_completed_phase(phase_name)
                cumulative_weight += phase_weight
                self._update_overall_progress(cumulative_weight)

                logger.info(f"Phase {phase_name} completed: {result.get('status', 'ok')}")

            except asyncio.CancelledError:
                self._fail_phase_record(phase_record_id, "Cancelled")
                self._update_session_status("cancelled")
                summary["status"] = "cancelled"
                return summary

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Phase {phase_name} failed: {error_msg}", exc_info=True)
                self._fail_phase_record(phase_record_id, error_msg)
                self._update_session_status("failed", error=error_msg)
                summary["status"] = "failed"
                summary["error"] = error_msg
                summary["failed_phase"] = phase_name
                return summary

        # All phases completed
        self._update_session_status("completed")
        self._update_session_field("completed_at", datetime.utcnow())
        self._update_overall_progress(1.0)
        summary["status"] = "completed"

        logger.info("=" * 60)
        logger.info("AUTO PILOT - Pipeline Completed")
        logger.info("=" * 60)

        return summary

    # ------------------------------------------------------------------
    # Phase 1: Exploration
    # ------------------------------------------------------------------

    async def _run_exploration_phase(self, config: AutoPilotConfig, phase_id: int) -> dict[str, Any]:
        """Explore each entry URL to discover app structure."""
        exploration_ids: list[str] = []
        exploration_quality: list[dict[str, Any]] = []
        exploration_quality_by_session: dict[str, dict[str, Any]] = {}
        total_pages = 0
        total_flows = 0

        async def run_pass(pass_label: str, max_interactions: int, strategy: str, start_index: int = 0):
            nonlocal total_pages, total_flows
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

                logger.info(
                    "Exploration %s for %s done: %s pages, %s flows",
                    pass_label,
                    url,
                    result.pages_discovered,
                    len(result.flows),
                )

        await run_pass("initial", config.max_interactions, config.strategy)

        auto_retried = False
        if exploration_ids and self._is_weak_exploration(total_pages, total_flows):
            auto_retried = True
            retry_interactions = min(200, max(config.max_interactions * 2, config.max_interactions + 50, 100))
            logger.info(
                "Exploration evidence is weak (%s pages, %s flows); retrying with %s interactions",
                total_pages,
                total_flows,
                retry_interactions,
            )
            self._update_phase_step(
                phase_id,
                "Exploration found limited evidence; retrying with more interactions",
                items_total=len(config.entry_urls),
                items_completed=0,
            )
            await run_pass("auto_retry", retry_interactions, "breadth_first", start_index=len(exploration_ids))

        self._update_session_list("exploration_session_ids", exploration_ids)
        self._update_session_field("total_pages_discovered", total_pages)
        self._update_session_field("total_flows_discovered", total_flows)
        self._merge_session_config(
            {
                "ai_quality": {
                    "exploration": {
                        "sessions": exploration_quality,
                        "min_quality_score": min(
                            [q.get("quality_score", 0) for q in exploration_quality if q] or [0]
                        ),
                        "fallback_used": any(q.get("fallback_used") for q in exploration_quality if q),
                        "degraded_mode": any(q.get("degraded_mode") for q in exploration_quality if q),
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
                retry_interactions = min(200, max(config.max_interactions * 2, config.max_interactions + 50, 100))
                await run_pass("user_reexplore", retry_interactions, "breadth_first", start_index=len(exploration_ids))
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
            "fallback_ready": self._is_weak_exploration(total_pages, total_flows),
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

        explore_config = ExplorationConfig(
            entry_url=url,
            max_interactions=max_interactions,
            max_depth=config.max_depth,
            strategy=strategy,
            timeout_minutes=config.timeout_minutes,
            credentials=config.credentials,
            login_url=config.login_url,
            additional_instructions=config.instructions,
        )

        safe_label = re.sub(r"[^a-zA-Z0-9_]+", "_", pass_label).strip("_") or "pass"
        explore_session_id = f"{self.session_id}_explore_{url_index}_{safe_label}_{datetime.now().strftime('%H%M%S')}"

        await check_system_available("autopilot_exploration")

        pool = await get_browser_pool()
        async with pool.browser_slot(
            request_id=f"autopilot_{explore_session_id}",
            operation_type=OperationType.AUTOPILOT,
            description=f"AutoPilot exploration: {url}",
        ) as acquired:
            if not acquired:
                logger.warning(f"Failed to acquire browser slot for exploration of {url}")
                return None

            explorer = AppExplorer(project_id=config.project_id)
            result = await explorer.explore(explore_config, explore_session_id)
            self._store_exploration_results(explore_session_id, result, config.project_id)
            return result

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
        return total_flows == 0

    # ------------------------------------------------------------------
    # Phase 2: Requirements
    # ------------------------------------------------------------------

    async def _run_requirements_phase(self, config: AutoPilotConfig, phase_id: int) -> dict[str, Any]:
        """Extract requirements from exploration data."""
        from orchestrator.workflows.requirements_generator import RequirementsGenerator

        exploration_ids = self._get_session_exploration_ids()
        if not exploration_ids:
            logger.warning("No exploration sessions found, skipping requirements phase")
            return {"status": "skipped", "reason": "no_explorations"}
        usable_exploration_ids = self._filter_exploration_ids_by_quality(exploration_ids)
        if not usable_exploration_ids:
            logger.warning("No reliable exploration sessions found, skipping requirements phase")
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
            return {"status": "skipped", "reason": "quality_gate", "input_exploration_ids": exploration_ids}
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
                logger.info(f"Generated {result.total_requirements} requirements from exploration {explore_id}")
            except Exception as e:
                logger.warning(f"Requirements generation failed for {explore_id}: {e}")

        self._update_session_field("total_requirements_generated", len(all_requirements))

        self._update_phase_step(
            phase_id,
            "Requirements generation complete",
            items_total=len(exploration_ids),
            items_completed=len(exploration_ids),
        )

        # Ask question about generated requirements if reactive_mode
        if config.reactive_mode and all_requirements:
            req_summaries = [
                {"code": r.req_code, "title": r.title, "priority": r.priority} for r in all_requirements[:20]
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

    async def _run_test_ideas_phase(self, config: AutoPilotConfig, phase_id: int) -> dict[str, Any]:
        """Generate traceable test ideas and create spec tasks from them."""
        from orchestrator.workflows.test_idea_generator import TestIdeaGenerator

        exploration_ids = self._get_session_exploration_ids()
        if not exploration_ids:
            logger.warning("No exploration sessions found, skipping test idea phase")
            return {"status": "skipped", "reason": "no_explorations"}
        usable_exploration_ids = self._filter_exploration_ids_by_quality(exploration_ids)
        if not usable_exploration_ids:
            logger.warning("No reliable exploration sessions found, skipping test idea phase")
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
            return {"status": "skipped", "reason": "quality_gate", "input_exploration_ids": exploration_ids}
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
                logger.info(f"Generated {result.total_ideas} test ideas from exploration {explore_id}")
            except Exception as e:
                logger.warning(f"Test idea generation failed for {explore_id}: {e}")

        if all_ideas:
            self._create_spec_tasks_from_test_ideas(all_ideas)
        elif not self._has_spec_tasks():
            from orchestrator.memory.exploration_store import get_exploration_store

            store = get_exploration_store(project_id=config.project_id)
            requirements = [
                req for req in store.get_requirements() if req.source_session_id in set(exploration_ids)
            ]
            self._create_spec_tasks_from_requirements(requirements)

        self._update_phase_step(
            phase_id,
            "Test idea generation complete",
            items_total=len(exploration_ids),
            items_completed=len(exploration_ids),
        )

        if config.reactive_mode and all_ideas:
            idea_preview = [
                {"title": idea.title, "priority": idea.priority, "readiness": idea.spec_readiness}
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
        }

    # ------------------------------------------------------------------
    # Phase 4: Spec Generation
    # ------------------------------------------------------------------

    async def _run_spec_generation_phase(self, config: AutoPilotConfig, phase_id: int) -> dict[str, Any]:
        """Generate test spec markdown files from requirements, one at a time."""
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSpecTask

        # Load spec tasks sorted by priority
        with Session(engine) as db:
            stmt = (
                select(AutoPilotSpecTask)
                .where(AutoPilotSpecTask.session_id == self.session_id)
                .where(AutoPilotSpecTask.status.in_(["pending", "failed"]))
            )
            tasks = db.exec(stmt).all()

        # Sort by priority (critical first)
        threshold_level = PRIORITY_ORDER.get(self._effective_priority_threshold(config), 3)
        tasks = [t for t in tasks if PRIORITY_ORDER.get(t.priority, 3) <= threshold_level]
        tasks.sort(key=lambda t: PRIORITY_ORDER.get(t.priority, 3))

        # Enforce max_specs limit
        tasks = tasks[: config.max_specs]

        if not tasks:
            logger.warning("No spec tasks to generate; creating fallback tasks from exploration evidence")
            self._create_fallback_spec_tasks_from_exploration(config)
            with Session(engine) as db:
                stmt = (
                    select(AutoPilotSpecTask)
                    .where(AutoPilotSpecTask.session_id == self.session_id)
                    .where(AutoPilotSpecTask.status.in_(["pending", "failed"]))
                )
                tasks = db.exec(stmt).all()
            threshold_level = PRIORITY_ORDER.get(self._effective_priority_threshold(config), 3)
            tasks = [t for t in tasks if PRIORITY_ORDER.get(t.priority, 3) <= threshold_level]
            tasks.sort(key=lambda t: PRIORITY_ORDER.get(t.priority, 3))
            tasks = tasks[: config.max_specs]

        if not tasks:
            logger.warning("Fallback spec task creation produced no tasks; creating entry-page smoke task")
            self._create_entry_page_spec_task(config)
            with Session(engine) as db:
                stmt = (
                    select(AutoPilotSpecTask)
                    .where(AutoPilotSpecTask.session_id == self.session_id)
                    .where(AutoPilotSpecTask.status.in_(["pending", "failed"]))
                )
                tasks = db.exec(stmt).all()[: config.max_specs]

        specs_generated = 0
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
                    self._update_spec_task(task.id, "completed", spec_path=str(spec_path))
                    specs_generated += 1
                else:
                    self._update_spec_task(task.id, "failed", error="Spec generation returned empty")
            except Exception as e:
                logger.warning(f"Spec generation failed for task {task.id}: {e}")
                self._update_spec_task(task.id, "failed", error=str(e)[:500])

        self._update_session_field("total_specs_generated", specs_generated)

        self._update_phase_step(
            phase_id,
            "Spec generation complete",
            items_total=len(tasks),
            items_completed=len(tasks),
        )

        if specs_generated == 0:
            raise RuntimeError("Spec generation produced 0 specs")

        return {
            "status": "completed",
            "specs_generated": specs_generated,
            "total_tasks": len(tasks),
        }

    # ------------------------------------------------------------------
    # Phase 5: Test Generation
    # ------------------------------------------------------------------

    async def _run_test_generation_phase(self, config: AutoPilotConfig, phase_id: int) -> dict[str, Any]:
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

        async def _generate_one(test_task_id: int, spec_path: str, spec_name: str):
            nonlocal passed_count, failed_count

            async with semaphore:
                if self._cancelled.is_set():
                    return

                # Block if a load test is running
                await check_system_available("autopilot_test_generation")

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

                    self._update_test_task(test_task_id, "running")

                    # Create run directory
                    run_dir = Path("runs") / "autopilot" / self.session_id / Path(spec_name).stem
                    run_dir.mkdir(parents=True, exist_ok=True)

                    pipeline = FullNativePipeline(project_id=config.project_id)
                    try:
                        result = await pipeline.run(
                            spec_path=spec_path,
                            run_dir=run_dir,
                            browser="chromium",
                            hybrid_healing=config.hybrid_healing,
                        )

                        success = result.get("success", False)
                        test_path = result.get("test_path")

                        if success:
                            self._update_test_task(
                                test_task_id,
                                "passed",
                                passed=True,
                                test_path=test_path,
                            )
                            passed_count += 1
                        else:
                            self._update_test_task(
                                test_task_id,
                                "failed",
                                passed=False,
                                test_path=test_path,
                                error_summary=result.get("error", "Test failed")[:500],
                            )
                            failed_count += 1

                        results[test_task_id] = result

                    except Exception as e:
                        logger.error(
                            f"Test generation failed for {spec_name}: {e}",
                            exc_info=True,
                        )
                        self._update_test_task(
                            test_task_id,
                            "error",
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
        for tt_id, spec_path, spec_name in test_tasks:
            t = asyncio.create_task(_generate_one(tt_id, spec_path, spec_name))
            self._test_tasks[tt_id] = t

        await asyncio.gather(*self._test_tasks.values(), return_exceptions=True)
        self._test_tasks.clear()  # Clean up references

        self._update_session_field("total_tests_generated", total)
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
            "total": total,
            "passed": passed_count,
            "failed": failed_count,
        }

    # ------------------------------------------------------------------
    # Phase 6: Reporting
    # ------------------------------------------------------------------

    async def _run_reporting_phase(self, config: AutoPilotConfig, phase_id: int) -> dict[str, Any]:
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
                    use_ai_matching=True,
                )
                coverage_pct = rtm_result.coverage_percentage
                rtm_mappings = len(rtm_result.mappings)

                logger.info(f"RTM generated: {coverage_pct:.1f}% coverage, {rtm_mappings} mappings")
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
            auto_continue_at=datetime.utcnow() + timedelta(hours=self._config.auto_continue_hours),
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

        logger.info(f"Question {question_id} auto-continued with default: {default_answer}")

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

        def deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
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
                return session.phases_completed
        return []

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

    def _filter_exploration_ids_by_quality(self, exploration_ids: list[str]) -> list[str]:
        """Return exploration IDs that are reliable enough for downstream generation."""
        config = self._get_session_config()
        by_session = (
            config.get("ai_quality", {})
            .get("exploration", {})
            .get("by_session", {})
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
            if gated_out:
                gated[exploration_id] = reason or "quality_gate"
            else:
                usable.append(exploration_id)

        if gated:
            self._merge_session_config({"ai_quality": {"gated_explorations": gated}})
        return usable

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
                existing.error_message = None
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
                logger.warning(f"Skipping invalid transition {t.sequence}: {invalid_reason}")
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
                flow_name = self._normalize_flow_name(flow.name, flow.category, flow.start_url, flow.end_url, idx)
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
                logger.warning(f"Failed to store API endpoint {endpoint.get('url')}: {ae}")

        # Store issues
        for issue in getattr(result, "issues", []) or []:
            valid, invalid_reason = is_valid_issue(issue)
            if not valid:
                logger.warning(f"Skipping invalid issue '{issue.issue_type}': {invalid_reason}")
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

    def _get_discovered_flow_names(self, exploration_ids: list[str], project_id: str) -> list[str]:
        """Get flow names from completed explorations."""
        from orchestrator.memory.exploration_store import get_exploration_store

        store = get_exploration_store(project_id=project_id)
        names = []
        for eid in exploration_ids:
            flows = store.get_session_flows(eid)
            if flows:
                for idx, f in enumerate(flows, 1):
                    names.append(self._normalize_flow_name(f.flow_name, f.flow_category, f.start_url, f.end_url, idx))
                continue

            for idx, flow in enumerate(self._load_flow_artifacts(eid), 1):
                names.append(
                    self._normalize_flow_name(
                        flow.get("name") or flow.get("title"),
                        flow.get("category"),
                        flow.get("startUrl") or flow.get("start_url") or flow.get("entry_point"),
                        flow.get("endUrl") or flow.get("end_url") or flow.get("exit_point"),
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
                        "ref": step.get("ref") or step.get("elementRef") or step.get("element_ref"),
                        "role": step.get("role") or step.get("elementRole") or step.get("element_role"),
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
        category_label = self._normalize_flow_category(category).replace("_", " ").title()
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
                return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
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

    def _create_fallback_spec_tasks_from_exploration(self, config: AutoPilotConfig) -> None:
        """Create deterministic spec tasks directly from exploration evidence."""
        from orchestrator.memory.exploration_store import get_exploration_store

        store = get_exploration_store(project_id=config.project_id)
        exploration_ids = self._get_session_exploration_ids()

        created = 0
        for eid in exploration_ids:
            flows = store.get_session_flows(eid)
            if flows:
                for flow in flows:
                    priority = "high" if flow.flow_category in {"authentication", "crud", "form_submission"} else "medium"
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

    def _create_spec_tasks_from_requirements(self, requirements):
        """Create AutoPilotSpecTask records for each requirement."""
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSpecTask

        with Session(engine) as db:
            existing_titles = set(
                db.exec(
                    select(AutoPilotSpecTask.requirement_title).where(
                        AutoPilotSpecTask.session_id == self.session_id
                    )
                ).all()
            )
            for req in requirements:
                if req.title in existing_titles:
                    continue
                task = AutoPilotSpecTask(
                    session_id=self.session_id,
                    requirement_id=getattr(req, "id", None),
                    requirement_title=req.title,
                    priority=req.priority,
                    status="pending",
                )
                db.add(task)
                existing_titles.add(req.title)
            db.commit()

    def _create_spec_tasks_from_test_ideas(self, test_ideas):
        """Create AutoPilotSpecTask records for generated test ideas."""
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSpecTask

        with Session(engine) as db:
            existing_titles = set(
                db.exec(
                    select(AutoPilotSpecTask.requirement_title).where(
                        AutoPilotSpecTask.session_id == self.session_id
                    )
                ).all()
            )
            for idea in test_ideas:
                if idea.title in existing_titles:
                    continue
                requirement_id = self._lookup_requirement_id_for_test_idea(idea)
                task = AutoPilotSpecTask(
                    session_id=self.session_id,
                    requirement_id=requirement_id,
                    requirement_title=idea.title,
                    priority=idea.priority,
                    status="pending",
                )
                db.add(task)
                existing_titles.add(idea.title)
            db.commit()

    def _has_spec_tasks(self) -> bool:
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSpecTask

        with Session(engine) as db:
            stmt = select(AutoPilotSpecTask).where(AutoPilotSpecTask.session_id == self.session_id).limit(1)
            return db.exec(stmt).first() is not None

    def _count_spec_tasks(self) -> int:
        from sqlalchemy import func

        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSpecTask

        with Session(engine) as db:
            stmt = select(func.count()).select_from(AutoPilotSpecTask).where(
                AutoPilotSpecTask.session_id == self.session_id
            )
            return int(db.exec(stmt).one())

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

        idea = self._get_test_idea_for_task(task.requirement_title, config.project_id) if task.requirement_title else None

        # Build spec content
        title = task.requirement_title or "Unnamed Test"
        safe_name = re.sub(r"[^\w\s-]", "", title.lower())
        safe_name = re.sub(r"[\s]+", "-", safe_name.strip())[:60]
        spec_filename = f"{safe_name}.md"
        spec_path = specs_dir / spec_filename

        # Determine target URL from exploration sessions
        target_url = config.entry_urls[0] if config.entry_urls else "https://example.com"

        # Build steps from requirement and exploration data
        description_lines = []
        steps = []
        expected_outcomes = []

        if idea:
            description_lines.append(idea.get("description") or f"Test idea: {title}")
            steps = list(idea.get("suggested_steps") or [])
            expected_outcomes = list(idea.get("expected_outcomes") or [])
            source_requirements = idea.get("source_requirements") or []
            if source_requirements:
                description_lines.append(f"Source requirement(s): {', '.join(source_requirements[:5])}")
            source_flows = idea.get("source_flows") or []
            if source_flows:
                description_lines.append(f"Source flow(s): {', '.join(source_flows[:5])}")

        if req and not idea:
            description_lines.append(req.description or f"Test for: {req.title}")

            # Try to find matching flow for step details
            exploration_ids = self._get_session_exploration_ids()
            matching_flow = None
            for eid in exploration_ids:
                flows = store.get_session_flows(eid)
                for flow in flows:
                    # Simple name matching
                    if req.title.lower() in flow.flow_name.lower() or flow.flow_name.lower() in req.title.lower():
                        matching_flow = flow
                        break
                if matching_flow:
                    break

            if matching_flow:
                target_url = matching_flow.start_url or target_url
                flow_steps = store.get_flow_steps(matching_flow.id)
                for fs in flow_steps:
                    if fs.value is not None:
                        steps.append(
                            f'{fs.action_type.capitalize()} "{fs.value}" into the {fs.element_name or "field"}'
                        )
                    else:
                        steps.append(f"{fs.action_type.capitalize()} the {fs.element_name or 'element'}")

            # Acceptance criteria become expected outcomes
            if req.acceptance_criteria:
                expected_outcomes = list(req.acceptance_criteria)
        else:
            description_lines.append(f"Automated test for: {title}")

        # Fallback steps if none derived from flow
        if not steps:
            steps = [f"Navigate to {target_url}", f"Verify {title}"]

        if not expected_outcomes:
            expected_outcomes = [f"{title} works as expected"]

        # Build markdown
        spec_content = f"# Test: {title}\n\n"
        spec_content += "## Description\n"
        spec_content += "\n".join(description_lines) + "\n\n"
        spec_content += "## Steps\n"
        # Always start with navigation
        if not any("navigate" in s.lower() for s in steps):
            spec_content += f"1. Navigate to {target_url}\n"
            for i, step in enumerate(steps, 2):
                spec_content += f"{i}. {step}\n"
        else:
            for i, step in enumerate(steps, 1):
                spec_content += f"{i}. {step}\n"
        spec_content += "\n## Expected Outcome\n"
        for outcome in expected_outcomes:
            spec_content += f"- {outcome}\n"

        spec_path.write_text(spec_content)
        logger.info(f"Generated spec: {spec_path}")
        return spec_path

    def _get_test_idea_for_task(self, title: str, project_id: str) -> dict[str, Any] | None:
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
            source_keys = {str(item).strip().lower() for item in idea.source_requirements if str(item).strip()}
            for req in requirements:
                if req.req_code.lower() in source_keys or req.title.strip().lower() in source_keys:
                    return req.id
        except Exception as exc:
            logger.debug(f"Unable to resolve requirement for test idea '{getattr(idea, 'title', '')}': {exc}")
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
                )
                existing = db.exec(stmt).first()

                if existing and existing.status in ("passed",):
                    # Already passed, skip
                    continue

                if existing and existing.status in ("pending", "failed", "error"):
                    # Re-attempt
                    existing.status = "pending"
                    existing.error_summary = None
                    existing.started_at = None
                    existing.completed_at = None
                    db.add(existing)
                    db.commit()
                    db.refresh(existing)
                    result_tuples.append((existing.id, st.spec_path, st.spec_name or Path(st.spec_path).stem))
                    continue

                # Create new test task
                tt = AutoPilotTestTask(
                    session_id=self.session_id,
                    spec_task_id=st.id,
                    spec_name=st.spec_name or (Path(st.spec_path).stem if st.spec_path else None),
                    spec_path=st.spec_path,
                    status="pending",
                )
                db.add(tt)
                db.commit()
                db.refresh(tt)
                result_tuples.append((tt.id, st.spec_path, tt.spec_name or "unknown"))

        return result_tuples

    def _update_test_task(
        self,
        task_id: int,
        status: str,
        passed: bool = None,
        test_path: str = None,
        error_summary: str = None,
    ):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotTestTask

        with Session(engine) as db:
            task = db.get(AutoPilotTestTask, task_id)
            if task:
                task.status = status
                if passed is not None:
                    task.passed = passed
                if test_path:
                    task.test_path = test_path
                if error_summary:
                    task.error_summary = error_summary[:1000]
                if status == "running":
                    task.started_at = datetime.utcnow()
                if status in ("passed", "failed", "error"):
                    task.completed_at = datetime.utcnow()
                db.add(task)
                db.commit()
