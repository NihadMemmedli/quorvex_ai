"""Versioned prompt metadata helpers.

The current workflows build large prompts dynamically. This module gives each
rendered prompt a stable identity and hash without forcing all prompt text into
a separate template system at once.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class PromptMetadata:
    """Metadata attached to one rendered prompt."""

    prompt_id: str
    version: str
    stage: str
    schema_name: str | None
    rendered_prompt_hash: str
    rendered_at: str
    owner: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_prompt_metadata(
    *,
    prompt_id: str,
    version: str,
    stage: str,
    schema_name: str | None,
    rendered_prompt: str,
    owner: str = "system",
) -> PromptMetadata:
    """Create metadata for a rendered prompt."""

    digest = hashlib.sha256(rendered_prompt.encode("utf-8")).hexdigest()
    return PromptMetadata(
        prompt_id=prompt_id,
        version=version,
        stage=stage,
        schema_name=schema_name,
        rendered_prompt_hash=digest,
        rendered_at=datetime.now(timezone.utc).isoformat(),
        owner=owner,
    )


def attach_prompt_metadata(prompt: str, metadata: PromptMetadata) -> str:
    """Prefix a prompt with compact machine-readable metadata."""

    header = (
        "<prompt_metadata "
        f'id="{metadata.prompt_id}" '
        f'version="{metadata.version}" '
        f'stage="{metadata.stage}" '
        f'schema="{metadata.schema_name or ""}" '
        f'hash="{metadata.rendered_prompt_hash}"'
        " />"
    )
    return f"{header}\n\n{prompt}"
