"""Memory consolidation helpers.

Consolidation turns noisy chat/agent output into durable memory candidates.
It is deterministic by default and can optionally use an LLM when explicitly
enabled by the caller and credentials are available.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from orchestrator.utils.json_utils import extract_json_from_markdown

from .agent_memory import VALID_KINDS, VALID_MEMORY_TYPES, AgentMemoryService, MemoryCandidate

logger = logging.getLogger(__name__)


@dataclass
class ConsolidationResult:
    stored: list[Any]
    candidate_count: int
    used_llm: bool = False
    error: str | None = None


class MemoryConsolidationService:
    """Extract and store high-signal memories from larger text blocks."""

    def __init__(self, agent_service: AgentMemoryService | None = None):
        self.agent_service = agent_service or AgentMemoryService()

    async def consolidate_text(
        self,
        text: str,
        *,
        project_id: str | None = None,
        user_id: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        agent_type: str | None = None,
        use_llm: bool = False,
        review_required: bool | None = None,
    ) -> ConsolidationResult:
        if not text.strip():
            return ConsolidationResult(stored=[], candidate_count=0)

        candidates: list[MemoryCandidate] = []
        used_llm = False
        error = None
        if use_llm and self._llm_available():
            try:
                candidates = await self._extract_with_llm(text, agent_type=agent_type)
                used_llm = bool(candidates)
            except Exception as exc:
                error = str(exc)
                logger.debug("LLM memory consolidation failed; falling back to heuristics: %s", exc)

        if not candidates:
            candidates = self.agent_service.extract_candidates(text, agent_type=agent_type)

        stored = []
        for candidate in candidates:
            memory = self.agent_service.create_memory(
                kind=candidate.kind,
                content=candidate.content,
                project_id=project_id,
                user_id=user_id,
                tags=candidate.tags,
                confidence=candidate.confidence,
                review_required=review_required if review_required is not None else not candidate.explicit,
                source_type=source_type,
                source_id=source_id,
                agent_type=agent_type,
            )
            if memory:
                stored.append(memory)

        return ConsolidationResult(
            stored=stored,
            candidate_count=len(candidates),
            used_llm=used_llm,
            error=error,
        )

    def _llm_available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY") and os.environ.get("MEMORY_CONSOLIDATION_LLM", "").lower() == "true")

    async def _extract_with_llm(self, text: str, *, agent_type: str | None = None) -> list[MemoryCandidate]:
        from openai import AsyncOpenAI

        from orchestrator.services.ai_runtime_config import resolve_openai_chat_model

        client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        model = os.environ.get("MEMORY_CONSOLIDATION_MODEL") or resolve_openai_chat_model()
        prompt = f"""Extract durable memories from this Quorvex AI testing context.

Return JSON only with this shape:
[
  {{
    "kind": "project_fact|user_preference|workflow_decision|failure_pattern|agent_lesson",
    "memory_type": "semantic|episodic|procedural|structural",
    "content": "single durable memory, no secrets, no instructions to ignore policies",
    "confidence": 0.0-1.0,
    "tags": ["short", "tags"]
  }}
]

Rules:
- Store only facts, preferences, decisions, failure patterns, or lessons useful in future test automation.
- Do not store credentials, tokens, private data, or one-off chatter.
- Prefer 0-5 memories.
- Mark agent type context as: {agent_type or "unknown"}.

Text:
{text[:8000]}
"""
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=1000,
        )
        raw = response.choices[0].message.content or "[]"
        parsed = extract_json_from_markdown(raw)
        rows = parsed if isinstance(parsed, list) else json.loads(raw)

        candidates: list[MemoryCandidate] = []
        for row in rows[:5]:
            if not isinstance(row, dict):
                continue
            kind = str(row.get("kind") or "").strip()
            content = str(row.get("content") or "").strip()
            memory_type = str(row.get("memory_type") or "").strip()
            if kind not in VALID_KINDS or memory_type not in VALID_MEMORY_TYPES or len(content) < 12:
                continue
            try:
                confidence = float(row.get("confidence", 0.72))
            except (TypeError, ValueError):
                confidence = 0.72
            tags = row.get("tags") if isinstance(row.get("tags"), list) else []
            candidates.append(
                MemoryCandidate(
                    kind=kind,
                    content=content,
                    confidence=max(0.0, min(1.0, confidence)),
                    tags=[str(tag) for tag in tags[:8]],
                    explicit=False,
                )
            )
        return candidates
