"""Memory effectiveness attribution and conservative repair actions."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from orchestrator.api import db as db_module
from orchestrator.api.models_db import (
    AgentMemory,
    MemoryFeedbackAggregate,
    MemoryInjectionEvent,
)

from .agent_memory import get_agent_memory_service
from .feedback import get_memory_feedback_service


def _utcnow() -> datetime:
    return datetime.utcnow()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _all_injected_memory_ids(event: MemoryInjectionEvent) -> list[str]:
    ids = list(event.memory_ids)
    graph_ids = (event.extra_data or {}).get("graph_expanded_memory_ids")
    if isinstance(graph_ids, list):
        ids.extend(str(memory_id) for memory_id in graph_ids if memory_id)
    return list(dict.fromkeys(ids))


def _event_extra(event: MemoryInjectionEvent) -> dict[str, Any]:
    return dict(event.extra_data or {})


class MemoryEffectivenessService:
    """Correlate prompt-memory injections with outcomes and feedback."""

    def summarize(
        self,
        *,
        project_id: str | None = None,
        days: int = 30,
        stage: str | None = None,
    ) -> dict[str, Any]:
        cutoff = _utcnow() - timedelta(days=max(1, days))
        with Session(db_module.engine) as session:
            statement = select(MemoryInjectionEvent).where(MemoryInjectionEvent.created_at >= cutoff)
            if project_id:
                statement = statement.where(MemoryInjectionEvent.project_id == project_id)
            if stage:
                statement = statement.where(MemoryInjectionEvent.stage == stage)
            events = list(session.exec(statement.order_by(MemoryInjectionEvent.created_at.desc())).all())

            memory_ids = [memory_id for event in events for memory_id in _all_injected_memory_ids(event)]
            memory_ids = list(dict.fromkeys(memory_ids))
            memories = {
                memory.id: memory
                for memory in session.exec(select(AgentMemory).where(AgentMemory.id.in_(memory_ids))).all()
            } if memory_ids else {}
            feedback = get_memory_feedback_service(session).get_memory_feedback_stats(
                project_id=project_id,
                memory_ids=memory_ids,
            )

            stage_stats = self._stage_stats(events)
            memory_stats = self._memory_stats(events, memories, feedback)
            empty_recall_stages = sorted(
                stage
                for stage, rows in self._events_by_stage(events).items()
                if rows and all(not _all_injected_memory_ids(row) for row in rows)
            )
            stale_injections = self._stale_injections(events, memories)
            helpful = sorted(memory_stats, key=lambda item: (item["successes"], item["feedback_score"], item["injections"]), reverse=True)[:10]
            harmful = sorted(memory_stats, key=lambda item: (item["failures"], -item["feedback_score"], item["injections"]), reverse=True)[:10]

            return {
                "project_id": project_id,
                "days": days,
                "stage": stage,
                "generated_at": _iso(_utcnow()),
                "total_injections": len(events),
                "stage_stats": stage_stats,
                "top_helpful_memories": helpful,
                "top_harmful_memories": harmful,
                "empty_recall_stages": empty_recall_stages,
                "stale_injections": stale_injections[:25],
                "recommended_actions": self._recommended_actions(
                    events=events,
                    empty_recall_stages=empty_recall_stages,
                    stale_injections=stale_injections,
                    harmful=harmful,
                ),
            }

    def attribute_outcome(
        self,
        *,
        project_id: str | None,
        success: bool,
        outcome_status: str,
        stage: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        run_id: str | None = None,
        test_path: str | None = None,
        spec_path: str | None = None,
        lookback_hours: int = 24,
    ) -> dict[str, Any]:
        cutoff = _utcnow() - timedelta(hours=max(1, lookback_hours))
        rating = "up" if success else "down"
        with Session(db_module.engine) as session:
            statement = select(MemoryInjectionEvent).where(MemoryInjectionEvent.created_at >= cutoff)
            if project_id:
                statement = statement.where(MemoryInjectionEvent.project_id == project_id)
            if stage:
                statement = statement.where(MemoryInjectionEvent.stage == stage)
            events = list(session.exec(statement.order_by(MemoryInjectionEvent.created_at.desc())).all())
            matched = [
                event for event in events
                if self._matches_outcome(
                    event,
                    source_type=source_type,
                    source_id=source_id,
                    run_id=run_id,
                    test_path=test_path,
                    spec_path=spec_path,
                )
            ]
            feedback_service = get_memory_feedback_service(session)
            feedback_count = 0
            for event in matched:
                extra = _event_extra(event)
                extra["outcome_status"] = outcome_status
                extra["outcome_success"] = success
                if run_id:
                    extra["run_id"] = run_id
                if test_path:
                    extra["test_path"] = test_path
                if spec_path:
                    extra["spec_path"] = spec_path
                event.extra_data = extra
                session.add(event)
                result = feedback_service.apply_feedback_to_injection(
                    event.id,
                    rating=rating,
                    source="system_outcome",
                    comment=f"Outcome attribution: {outcome_status}",
                )
                feedback_count += int(result.get("count") or 0)
            session.commit()
            return {
                "matched_injections": len(matched),
                "feedback_count": feedback_count,
                "rating": rating,
                "outcome_status": outcome_status,
            }

    def _matches_outcome(
        self,
        event: MemoryInjectionEvent,
        *,
        source_type: str | None,
        source_id: str | None,
        run_id: str | None,
        test_path: str | None,
        spec_path: str | None,
    ) -> bool:
        extra = _event_extra(event)
        if run_id:
            for key in ("run_id", "pipeline_run_id", "agent_run_id"):
                if str(extra.get(key) or "") == run_id:
                    return True
        if test_path and str(extra.get("test_path") or event.source_id or "") == test_path:
            return True
        if spec_path and str(extra.get("spec_path") or event.source_id or "") == spec_path:
            return True
        if source_id and event.source_id == source_id:
            return source_type is None or event.source_type == source_type
        return False

    def _events_by_stage(self, events: list[MemoryInjectionEvent]) -> dict[str, list[MemoryInjectionEvent]]:
        grouped: dict[str, list[MemoryInjectionEvent]] = defaultdict(list)
        for event in events:
            grouped[event.stage].append(event)
        return grouped

    def _stage_stats(self, events: list[MemoryInjectionEvent]) -> list[dict[str, Any]]:
        rows = []
        for stage, grouped in sorted(self._events_by_stage(events).items()):
            successes = sum(1 for event in grouped if (_event_extra(event).get("outcome_success") is True))
            failures = sum(1 for event in grouped if (_event_extra(event).get("outcome_success") is False))
            empty = sum(1 for event in grouped if not _all_injected_memory_ids(event))
            total_with_outcome = successes + failures
            rows.append(
                {
                    "stage": stage,
                    "injections": len(grouped),
                    "successes": successes,
                    "failures": failures,
                    "empty_recall": empty,
                    "success_rate": round(successes / total_with_outcome, 3) if total_with_outcome else None,
                    "last_injected_at": _iso(max((event.created_at for event in grouped), default=None)),
                }
            )
        return rows

    def _memory_stats(
        self,
        events: list[MemoryInjectionEvent],
        memories: dict[str, AgentMemory],
        feedback: dict[str, Any],
    ) -> list[dict[str, Any]]:
        stats: dict[str, dict[str, Any]] = {}
        for event in events:
            success = _event_extra(event).get("outcome_success")
            for memory_id in _all_injected_memory_ids(event):
                memory = memories.get(memory_id)
                item = stats.setdefault(
                    memory_id,
                    {
                        "memory_id": memory_id,
                        "summary": (memory.summary or memory.content) if memory else "Missing memory",
                        "kind": memory.kind if memory else "missing",
                        "injections": 0,
                        "successes": 0,
                        "failures": 0,
                        "feedback_score": 0.0,
                        "positive_feedback_count": 0,
                        "negative_feedback_count": 0,
                        "missing": memory is None,
                    },
                )
                item["injections"] += 1
                if success is True:
                    item["successes"] += 1
                elif success is False:
                    item["failures"] += 1
        for memory_id, item in stats.items():
            feedback_item = feedback.get(memory_id)
            if feedback_item:
                item["feedback_score"] = feedback_item.feedback_score
                item["positive_feedback_count"] = feedback_item.positive_feedback_count
                item["negative_feedback_count"] = feedback_item.negative_feedback_count
        return list(stats.values())

    def _stale_injections(
        self,
        events: list[MemoryInjectionEvent],
        memories: dict[str, AgentMemory],
    ) -> list[dict[str, Any]]:
        rows = []
        for event in events:
            for memory_id in _all_injected_memory_ids(event):
                memory = memories.get(memory_id)
                if not memory:
                    continue
                warning = None
                if memory.review_required:
                    warning = "review_required"
                elif memory.last_verified_at is None and (memory.importance or 0) >= 0.75:
                    warning = "high_importance_unverified"
                if warning:
                    rows.append(
                        {
                            "injection_id": event.id,
                            "memory_id": memory_id,
                            "stage": event.stage,
                            "warning": warning,
                            "summary": memory.summary or memory.content,
                            "created_at": _iso(event.created_at),
                        }
                    )
        return rows

    def _recommended_actions(
        self,
        *,
        events: list[MemoryInjectionEvent],
        empty_recall_stages: list[str],
        stale_injections: list[dict[str, Any]],
        harmful: list[dict[str, Any]],
    ) -> list[str]:
        actions = []
        if not events:
            actions.append("Run a memory-enabled planner, generator, healer, or autonomous workflow to collect effectiveness telemetry.")
        if empty_recall_stages:
            actions.append("Seed or approve memories for stages with empty recall.")
        if stale_injections:
            actions.append("Verify stale or review-required memories that were injected.")
        if any(item["failures"] > item["successes"] for item in harmful[:3]):
            actions.append("Review memories associated with failed outcomes and archive low-trust items.")
        return actions


class MemoryRepairService:
    """Conservative memory repair actions. Never deletes or auto-approves."""

    def run(self, *, project_id: str | None, action: str, dry_run: bool = True) -> dict[str, Any]:
        if action == "rebuild_graph":
            return self._rebuild_graph(project_id=project_id, dry_run=dry_run)
        if action == "mark_missing_injection_refs":
            return self._mark_missing_injection_refs(project_id=project_id, dry_run=dry_run)
        if action == "verify_stale":
            return self._verify_stale(project_id=project_id, dry_run=dry_run)
        if action == "archive_low_trust":
            return self._archive_low_trust(project_id=project_id, dry_run=dry_run)
        raise ValueError(f"Unsupported memory repair action: {action}")

    def _rebuild_graph(self, *, project_id: str | None, dry_run: bool) -> dict[str, Any]:
        if dry_run:
            with Session(db_module.engine) as session:
                count = session.exec(
                    select(AgentMemory).where(AgentMemory.project_id == project_id) if project_id else select(AgentMemory)
                ).all()
            return {"action": "rebuild_graph", "dry_run": True, "changed_count": len(count), "items": [], "warnings": []}
        from .knowledge_graph import get_memory_knowledge_graph_service

        result = get_memory_knowledge_graph_service().rebuild(project_id=project_id, include_review_required=False, use_llm=False)
        return {"action": "rebuild_graph", "dry_run": False, "changed_count": result.get("memories", 0), "items": [result], "warnings": []}

    def _mark_missing_injection_refs(self, *, project_id: str | None, dry_run: bool) -> dict[str, Any]:
        with Session(db_module.engine) as session:
            memories = {memory.id for memory in session.exec(select(AgentMemory)).all()}
            statement = select(MemoryInjectionEvent)
            if project_id:
                statement = statement.where(MemoryInjectionEvent.project_id == project_id)
            events = session.exec(statement).all()
            changed = []
            for event in events:
                missing = [memory_id for memory_id in _all_injected_memory_ids(event) if memory_id not in memories]
                if not missing:
                    continue
                changed.append({"injection_id": event.id, "missing_memory_ids": missing})
                if not dry_run:
                    extra = _event_extra(event)
                    extra["missing_memory_ids"] = missing
                    extra["memory_reference_status"] = "missing_refs"
                    event.extra_data = extra
                    session.add(event)
            if not dry_run:
                session.commit()
            return {"action": "mark_missing_injection_refs", "dry_run": dry_run, "changed_count": len(changed), "items": changed[:50], "warnings": []}

    def _verify_stale(self, *, project_id: str | None, dry_run: bool) -> dict[str, Any]:
        if dry_run:
            with Session(db_module.engine) as session:
                statement = select(AgentMemory).where(AgentMemory.status == "active")
                if project_id:
                    statement = statement.where(AgentMemory.project_id == project_id)
                rows = session.exec(statement).all()
                stale = [
                    memory for memory in rows
                    if memory.last_verified_at is None and (memory.importance or 0) >= 0.75
                ]
            return {
                "action": "verify_stale",
                "dry_run": True,
                "changed_count": len(stale),
                "items": [{"memory_id": memory.id, "summary": memory.summary or memory.content} for memory in stale[:50]],
                "warnings": [],
            }
        result = get_agent_memory_service().verify_stale(project_id=project_id, older_than_days=30, limit=100)
        memories = result.pop("memories", [])
        return {
            "action": "verify_stale",
            "dry_run": False,
            "changed_count": int(result.get("checked", 0)),
            "items": [{"memory_id": memory.id, "review_required": memory.review_required} for memory in memories[:50]],
            "warnings": [],
        }

    def _archive_low_trust(self, *, project_id: str | None, dry_run: bool) -> dict[str, Any]:
        with Session(db_module.engine) as session:
            statement = select(AgentMemory, MemoryFeedbackAggregate).join(
                MemoryFeedbackAggregate,
                MemoryFeedbackAggregate.memory_id == AgentMemory.id,
            ).where(AgentMemory.status == "active")
            if project_id:
                statement = statement.where(AgentMemory.project_id == project_id)
            pairs = session.exec(statement).all()
            candidates = [
                memory for memory, aggregate in pairs
                if (memory.confidence or 0) <= 0.45 and (aggregate.feedback_score or 0) < 0
            ]
            for memory in candidates:
                if not dry_run:
                    memory.status = "archived"
                    memory.updated_at = _utcnow()
                    session.add(memory)
            if not dry_run:
                session.commit()
            return {
                "action": "archive_low_trust",
                "dry_run": dry_run,
                "changed_count": len(candidates),
                "items": [{"memory_id": memory.id, "summary": memory.summary or memory.content} for memory in candidates[:50]],
                "warnings": ["Archived memories are not deleted and can be restored manually."] if candidates and not dry_run else [],
            }


def get_memory_effectiveness_service() -> MemoryEffectivenessService:
    return MemoryEffectivenessService()


def get_memory_repair_service() -> MemoryRepairService:
    return MemoryRepairService()
