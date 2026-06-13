"""Shared token estimation, context budgeting, and agent telemetry helpers."""

from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass
from typing import Any


_ENCODER = None
_ENCODER_ATTEMPTED = False


def estimate_tokens(text: str | None) -> int:
    """Estimate tokens with tiktoken when available, otherwise use a safe char fallback."""
    if not text:
        return 0
    global _ENCODER, _ENCODER_ATTEMPTED
    if not _ENCODER_ATTEMPTED:
        _ENCODER_ATTEMPTED = True
        try:
            import tiktoken

            _ENCODER = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _ENCODER = None
    if _ENCODER is not None:
        try:
            return len(_ENCODER.encode(text))
        except Exception:
            pass
    return max(1, math.ceil(len(text) / 3.5))


def prompt_hash(text: str | None) -> str | None:
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def context_budget_for_stage(stage: str | None, default_tokens: int) -> int:
    """Return the token budget for a stage, honoring AGENT_CONTEXT_BUDGET_<STAGE>."""
    keys = []
    if stage:
        normalized = re.sub(r"[^A-Za-z0-9]+", "_", stage).strip("_").upper()
        if normalized:
            keys.append(f"AGENT_CONTEXT_BUDGET_{normalized}")
    keys.append("AGENT_CONTEXT_BUDGET")
    for key in keys:
        value = os.environ.get(key)
        if not value:
            continue
        try:
            return max(0, int(value))
        except ValueError:
            continue
    return max(0, int(default_tokens))


def truncate_text_to_tokens(text: str | None, token_budget: int, *, marker: str = "\n...[truncated]...\n") -> str:
    """Trim text to an approximate token budget, preserving head and tail context."""
    text = text or ""
    token_budget = max(0, int(token_budget))
    if not text or token_budget <= 0:
        return ""
    if estimate_tokens(text) <= token_budget:
        return text
    char_budget = max(1, int(token_budget * 3.5))
    if len(text) <= char_budget:
        return text
    marker_len = len(marker)
    if char_budget <= marker_len + 20:
        return text[:char_budget].rstrip()
    head = (char_budget - marker_len) // 2
    tail = char_budget - marker_len - head
    return f"{text[:head].rstrip()}{marker}{text[-tail:].lstrip()}"


def clip_text(text: str | None, char_budget: int) -> str:
    text = text or ""
    if char_budget <= 0:
        return ""
    return text if len(text) <= char_budget else text[: max(0, char_budget - 3)].rstrip() + "..."


def extract_provider_usage(value: Any) -> dict[str, Any]:
    """Normalize common provider/SDK usage shapes into a compact dict."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        attrs = (
            "usage",
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "cached_input_tokens",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
        )
        data = {name: getattr(value, name) for name in attrs if hasattr(value, name)}
        if "usage" in data and isinstance(data["usage"], dict):
            nested = data.pop("usage")
            data.update(nested)
        value = data
    if not isinstance(value, dict):
        return {}
    usage = value.get("usage") if isinstance(value.get("usage"), dict) else value
    aliases = {
        "input_tokens": ("input_tokens", "prompt_tokens"),
        "output_tokens": ("output_tokens", "completion_tokens"),
        "total_tokens": ("total_tokens",),
        "cached_input_tokens": ("cached_input_tokens", "cache_read_input_tokens", "prompt_cache_hit_tokens"),
        "cache_creation_input_tokens": ("cache_creation_input_tokens", "prompt_cache_miss_tokens"),
    }
    normalized: dict[str, Any] = {}
    for canonical, keys in aliases.items():
        for key in keys:
            raw = usage.get(key)
            if raw is None:
                continue
            try:
                normalized[canonical] = int(raw)
                break
            except (TypeError, ValueError):
                continue
    return normalized


@dataclass
class AgentTokenTelemetry:
    stage: str | None
    agent_type: str | None
    model: str | None
    model_tier: str | None
    prompt_hash: str | None
    prompt_chars: int
    estimated_input_tokens: int
    output_chars: int
    estimated_output_tokens: int
    memory_chars: int
    estimated_memory_tokens: int
    provider_usage: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "stage": self.stage,
            "agent_type": self.agent_type,
            "model": self.model,
            "model_tier": self.model_tier,
            "prompt_hash": self.prompt_hash,
            "prompt_chars": self.prompt_chars,
            "estimated_input_tokens": self.estimated_input_tokens,
            "output_chars": self.output_chars,
            "estimated_output_tokens": self.estimated_output_tokens,
            "memory_chars": self.memory_chars,
            "estimated_memory_tokens": self.estimated_memory_tokens,
        }
        payload.update({f"provider_{key}": value for key, value in self.provider_usage.items()})
        if "input_tokens" in self.provider_usage:
            payload["input_tokens"] = self.provider_usage["input_tokens"]
        if "output_tokens" in self.provider_usage:
            payload["output_tokens"] = self.provider_usage["output_tokens"]
        if "cached_input_tokens" in self.provider_usage:
            payload["cached_input_tokens"] = self.provider_usage["cached_input_tokens"]
        return payload


def build_agent_token_telemetry(
    *,
    prompt: str | None,
    output: str | None,
    memory_context: str | None = None,
    stage: str | None = None,
    agent_type: str | None = None,
    model: str | None = None,
    model_tier: str | None = None,
    provider_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider_usage = extract_provider_usage(provider_usage or {})
    telemetry = AgentTokenTelemetry(
        stage=stage,
        agent_type=agent_type,
        model=model,
        model_tier=model_tier,
        prompt_hash=prompt_hash(prompt),
        prompt_chars=len(prompt or ""),
        estimated_input_tokens=estimate_tokens(prompt),
        output_chars=len(output or ""),
        estimated_output_tokens=estimate_tokens(output),
        memory_chars=len(memory_context or ""),
        estimated_memory_tokens=estimate_tokens(memory_context),
        provider_usage=provider_usage,
    )
    return telemetry.to_dict()
