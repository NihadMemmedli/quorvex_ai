"""Context labeling helpers for AI workflow stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SOURCE_OBSERVED = "observed"
SOURCE_INFERRED = "inferred"
SOURCE_FALLBACK = "fallback"
SOURCE_USER_PROVIDED = "user_provided"

VALID_SOURCE_TYPES = {
    SOURCE_OBSERVED,
    SOURCE_INFERRED,
    SOURCE_FALLBACK,
    SOURCE_USER_PROVIDED,
}


@dataclass
class ContextItem:
    """One labeled context payload passed to an AI stage."""

    name: str
    source_type: str
    content: Any
    confidence: float = 1.0
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContextBundle:
    """A stage-level context bundle with provenance labels."""

    stage: str
    items: list[ContextItem] = field(default_factory=list)

    def add(
        self,
        name: str,
        content: Any,
        *,
        source_type: str = SOURCE_OBSERVED,
        confidence: float = 1.0,
        notes: str | None = None,
    ) -> None:
        if source_type not in VALID_SOURCE_TYPES:
            source_type = SOURCE_INFERRED
        self.items.append(
            ContextItem(
                name=name,
                source_type=source_type,
                content=content,
                confidence=max(0.0, min(1.0, confidence)),
                notes=notes,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "items": [item.to_dict() for item in self.items]}

