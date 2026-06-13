"""Shared prompt augmentation for agent runtimes."""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from orchestrator.utils.token_budget import context_budget_for_stage, estimate_tokens

logger = logging.getLogger(__name__)


@dataclass
class PromptAugmentationResult:
    prompt: str
    context_text: str = ""
    injected: bool = False
    bundle: dict[str, Any] = field(default_factory=dict)
    telemetry: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _memory_project_id(explicit_project_id: str | None = None) -> str | None:
    return explicit_project_id or os.environ.get("MEMORY_PROJECT_ID") or os.environ.get("PROJECT_ID")


def augment_prompt_with_agent_memory(
    prompt: str,
    *,
    inject_memory: bool = True,
    project_id: str | None = None,
    agent_type: str = "AgentRunner",
    stage: str = "agent_runner",
    source_type: str | None = "agent_run",
    source_id: str | None = None,
    owner_type: str | None = None,
    owner_id: str | None = None,
    trace_agent_run_id: str | None = None,
    trace_id: str | None = None,
    runtime: str = "claude_sdk",
    model: str | None = None,
    model_tier: str | None = None,
    allowed_tools: list[str] | None = None,
    user_id: str | None = None,
) -> PromptAugmentationResult:
    """Inject scoped memory context and record telemetry.

    The helper is best-effort by design: memory retrieval failure must never
    fail an agent run.
    """

    if not inject_memory or os.environ.get("MEMORY_ENABLED", "true").lower() != "true":
        return PromptAugmentationResult(prompt=prompt, trace_id=trace_id)
    resolved_project_id = _memory_project_id(project_id)
    if not resolved_project_id:
        return PromptAugmentationResult(prompt=prompt, trace_id=trace_id)
    try:
        from orchestrator.memory.agent_memory import get_agent_memory_service
        from orchestrator.memory.context_builder import MemoryContextBuilder
        from orchestrator.memory.telemetry import record_memory_injection

        builder = MemoryContextBuilder(service=get_agent_memory_service())
        bundle = builder.build_bundle(
            query=prompt[:2000],
            project_id=resolved_project_id,
            user_id=user_id,
            agent_type=agent_type,
            limit=8,
        )
        token_budget = context_budget_for_stage(stage, 1200)
        context = builder.format_prompt_context(bundle, token_budget=token_budget)
        if not context:
            return PromptAugmentationResult(prompt=prompt, trace_id=trace_id)
        bundle_dict = bundle.to_dict()
        unified = bundle_dict.get("unified") or {}
        ranking = unified.get("ranking") or {}
        retrieved = unified.get("retrieved_knowledge") or {}
        prompt_hash = _sha256_text(prompt)
        span_id = None
        updated_trace_id = trace_id
        if trace_agent_run_id:
            try:
                from orchestrator.services.agent_trace import ensure_trace_snapshot, record_trace_span

                snapshot = ensure_trace_snapshot(
                    run_id=trace_agent_run_id,
                    prompt=prompt,
                    memory_context=context,
                    runtime=runtime,
                    model=model,
                    model_tier=model_tier,
                    allowed_tools=allowed_tools or [],
                )
                if snapshot:
                    updated_trace_id = snapshot.id
                span = record_trace_span(
                    run_id=trace_agent_run_id,
                    trace_id=updated_trace_id,
                    span_type="memory_injection",
                    name="Memory injection",
                    message="Agent memory context injected into prompt.",
                    payload={
                        "prompt_hash": prompt_hash,
                        "retriever_name": (retrieved.get("diagnostics") or {}).get("retriever"),
                        "source_list": sorted({item.get("source") for item in retrieved.get("items", []) if item.get("source")}),
                        "selected_items": ranking.get("selected_items", []),
                        "score_summary": ranking.get("score_summary", {}),
                        "citations": retrieved.get("citations", []),
                        "context_characters": len(context),
                        "context_tokens_estimated": estimate_tokens(context),
                        "context_budget_tokens": token_budget,
                    },
                )
                span_id = span.id if span else None
            except Exception as exc:
                logger.debug("Agent trace memory span skipped: %s", exc)
        telemetry = {
            "agent_type": agent_type,
            "owner_type": owner_type,
            "owner_id": owner_id,
            "agent_run_id": trace_agent_run_id,
            "trace_id": updated_trace_id,
            "span_id": span_id,
            "prompt_hash": prompt_hash,
            **({"run_id": source_id} if source_id else {}),
            "empty_recall": not bool(ranking.get("selected_items") or retrieved.get("items")),
            "memory_score_summary": ranking.get("score_summary", {}),
            "retriever_name": (retrieved.get("diagnostics") or {}).get("retriever"),
            "source_list": sorted({item.get("source") for item in retrieved.get("items", []) if item.get("source")}),
            "query_plan": [prompt[:500]],
            "chunk_ids": [item.get("id") for item in retrieved.get("items", []) if item.get("id")],
            "selected_count": (retrieved.get("diagnostics") or {}).get("selected_count"),
            "rejected_count": len(ranking.get("rejected_candidates") or []),
            "fallback_reason": None if retrieved.get("items") else "empty_retrieval",
            "context_tokens_estimated": estimate_tokens(context),
            "context_budget_tokens": token_budget,
        }
        record_memory_injection(
            project_id=resolved_project_id,
            actor_type="agent",
            stage=stage,
            query=prompt[:1000],
            bundle=bundle_dict,
            context_text=context,
            source_type=source_type,
            source_id=source_id or owner_id,
            extra_data=telemetry,
        )
        return PromptAugmentationResult(
            prompt=f"{context}\n\n---\n\n{prompt}",
            context_text=context,
            injected=True,
            bundle=bundle_dict,
            telemetry=telemetry,
            trace_id=updated_trace_id,
        )
    except Exception as exc:
        logger.debug("Agent memory retrieval skipped: %s", exc)
        return PromptAugmentationResult(prompt=prompt, trace_id=trace_id)
