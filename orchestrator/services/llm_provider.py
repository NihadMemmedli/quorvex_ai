"""
LLM Provider Client - Universal OpenAI-compatible client for LLM testing.

Supports any OpenAI-compatible API: OpenAI, Anthropic (via proxy), OpenRouter,
Ollama, Azure, and custom endpoints. Tracks latency, tokens, and cost.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Token pricing per 1M tokens: {model_prefix: (input_per_1m, output_per_1m)}
MODEL_PRICING: dict[str, tuple] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "claude-3-opus": (15.00, 75.00),
    "claude-3-sonnet": (3.00, 15.00),
    "claude-3-haiku": (0.25, 1.25),
    "claude-3.5-sonnet": (3.00, 15.00),
    "claude-3.5-haiku": (0.80, 4.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-opus-4": (15.00, 75.00),
    "o1-preview": (15.00, 60.00),
    "o1-mini": (3.00, 12.00),
    "deepseek-chat": (0.14, 0.28),
    "deepseek-reasoner": (0.55, 2.19),
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-2.0-flash": (0.10, 0.40),
    "llama-3.1-70b": (0.59, 0.79),
    "llama-3.1-8b": (0.06, 0.06),
    "mistral-large": (2.00, 6.00),
    "mixtral-8x7b": (0.24, 0.24),
    "qwen-2.5-72b": (0.59, 0.79),
}


@dataclass
class ProviderConfig:
    """Configuration for an LLM provider."""

    base_url: str
    api_key: str
    model_id: str
    default_temperature: float = 0.7
    default_max_tokens: int = 4096
    custom_pricing: tuple | None = None  # (input_per_1m, output_per_1m)
    timeout: int = 120


@dataclass
class LlmResponse:
    """Response from an LLM provider call."""

    output: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    model_id: str
    provider_id: str
    estimated_cost_usd: float
    error: str | None = None


def _estimate_tokens(text: str) -> int:
    """Estimate token count. Uses tiktoken if available, else chars/4."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def _estimate_cost(model_id: str, tokens_in: int, tokens_out: int, custom_pricing: tuple | None = None) -> float:
    """Estimate cost in USD based on model pricing."""
    if custom_pricing:
        input_rate, output_rate = custom_pricing
    else:
        input_rate, output_rate = 0.0, 0.0
        model_lower = model_id.lower()
        for prefix, pricing in MODEL_PRICING.items():
            if prefix in model_lower:
                input_rate, output_rate = pricing
                break

    cost = (tokens_in / 1_000_000 * input_rate) + (tokens_out / 1_000_000 * output_rate)
    return round(cost, 6)


class LlmProviderClient:
    """Universal LLM client using OpenAI-compatible API."""

    def __init__(self, config: ProviderConfig, provider_id: str = ""):
        self.config = config
        self.provider_id = provider_id
        self._client = None

    def _get_client(self):
        """Lazy-initialize the AsyncOpenAI client."""
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout,
            )
        return self._client

    async def call(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LlmResponse:
        """Send a chat completion request and track metrics.

        Args:
            messages: List of {"role": "...", "content": "..."} dicts
            temperature: Override default temperature
            max_tokens: Override default max tokens

        Returns:
            LlmResponse with output, metrics, and cost estimate
        """
        client = self._get_client()
        temp = temperature if temperature is not None else self.config.default_temperature
        max_tok = max_tokens or self.config.default_max_tokens

        start_ms = time.monotonic_ns() // 1_000_000

        try:
            response = await client.chat.completions.create(
                model=self.config.model_id,
                messages=messages,
                temperature=temp,
                max_tokens=max_tok,
            )

            latency_ms = (time.monotonic_ns() // 1_000_000) - start_ms

            # Extract output
            output = response.choices[0].message.content or ""

            # Get token counts from API response, fallback to estimation
            usage = response.usage
            if usage:
                tokens_in = usage.prompt_tokens or 0
                tokens_out = usage.completion_tokens or 0
            else:
                input_text = " ".join(m.get("content", "") for m in messages)
                tokens_in = _estimate_tokens(input_text)
                tokens_out = _estimate_tokens(output)

            cost = _estimate_cost(
                self.config.model_id,
                tokens_in,
                tokens_out,
                self.config.custom_pricing,
            )

            return LlmResponse(
                output=output,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
                model_id=self.config.model_id,
                provider_id=self.provider_id,
                estimated_cost_usd=cost,
            )

        except Exception as e:
            latency_ms = (time.monotonic_ns() // 1_000_000) - start_ms
            logger.error(f"LLM call failed for {self.config.model_id}: {e}")
            return LlmResponse(
                output="",
                tokens_in=0,
                tokens_out=0,
                latency_ms=latency_ms,
                model_id=self.config.model_id,
                provider_id=self.provider_id,
                estimated_cost_usd=0.0,
                error=str(e),
            )

    async def health_check(self) -> dict[str, Any]:
        """Verify provider reachability with a minimal request."""
        try:
            response = await self.call(
                messages=[{"role": "user", "content": "Say 'ok'"}],
                temperature=0.0,
                max_tokens=5,
            )
            if response.error:
                return {
                    "healthy": False,
                    "error": response.error,
                    "latency_ms": response.latency_ms,
                }
            return {
                "healthy": True,
                "latency_ms": response.latency_ms,
                "model": self.config.model_id,
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    async def close(self):
        """Close the underlying HTTP client."""
        if self._client:
            await self._client.close()
            self._client = None
