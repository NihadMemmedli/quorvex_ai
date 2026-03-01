"""
API Key Rotator - Thread-safe singleton for managing multiple Anthropic API keys.

Supports automatic failover on rate limit (429) errors with escalating cooldown.
Keys are loaded from ANTHROPIC_AUTH_TOKENS (comma-separated) or fall back to
a single ANTHROPIC_AUTH_TOKEN.
"""

import logging
import os
import re
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ApiKeySlot:
    """Tracks state for a single API key."""

    token: str
    index: int
    cooldown_until: float = 0.0  # monotonic timestamp
    consecutive_429s: int = 0
    total_429s: int = 0
    total_calls: int = 0

    @property
    def masked(self) -> str:
        """Return masked key for logging (first 4 + last 4 chars)."""
        if len(self.token) <= 8:
            return "****"
        return f"{self.token[:4]}...{self.token[-4:]}"

    @property
    def available(self) -> bool:
        """Check if key is currently available (not in cooldown)."""
        return time.monotonic() >= self.cooldown_until

    @property
    def cooldown_remaining(self) -> float:
        """Seconds remaining in cooldown (0 if available)."""
        remaining = self.cooldown_until - time.monotonic()
        return max(0.0, remaining)


# Escalating cooldown schedule (seconds)
_COOLDOWN_SCHEDULE = [60, 300, 900, 1800, 3600]  # 1m, 5m, 15m, 30m, 1h


def _get_cooldown_seconds(consecutive_429s: int) -> float:
    """Get cooldown duration based on consecutive 429 count."""
    idx = min(consecutive_429s - 1, len(_COOLDOWN_SCHEDULE) - 1)
    return float(_COOLDOWN_SCHEDULE[max(0, idx)])


def is_rate_limit_error(text: str) -> bool:
    """Check if error text indicates a rate limit / quota error."""
    lower = text.lower()
    indicators = ["429", "rate limit", "rate_limit", "usage limit", "too many requests", "quota"]
    return any(ind in lower for ind in indicators)


def parse_retry_after(text: str) -> float | None:
    """Try to extract a retry-after duration (in seconds) from an error message.

    Handles patterns like:
    - "Retry-After: 120"
    - "retry after 5 hours"
    - "Usage limit reached for 5 hour"
    - "try again in 30 minutes"
    """
    lower = text.lower()

    # "Retry-After: <seconds>" header
    m = re.search(r"retry[- ]after[:\s]+(\d+)", lower)
    if m:
        return float(m.group(1))

    # "N hour(s)" pattern
    m = re.search(r"(\d+)\s*hour", lower)
    if m:
        return float(m.group(1)) * 3600

    # "N minute(s)" pattern
    m = re.search(r"(\d+)\s*minute", lower)
    if m:
        return float(m.group(1)) * 60

    # "N second(s)" pattern
    m = re.search(r"(\d+)\s*second", lower)
    if m:
        return float(m.group(1))

    return None


class ApiKeyRotator:
    """Thread-safe manager for multiple API keys with cooldown tracking."""

    def __init__(self):
        self._slots: list[ApiKeySlot] = []
        self._lock = threading.Lock()
        self._round_robin_index = 0
        self._initialized = False

    def initialize(self):
        """Load keys from environment variables.

        Reads ANTHROPIC_AUTH_TOKENS (comma-separated) first, falls back to
        single ANTHROPIC_AUTH_TOKEN.
        """
        with self._lock:
            tokens_str = os.environ.get("ANTHROPIC_AUTH_TOKENS", "").strip()
            if tokens_str:
                tokens = [t.strip() for t in tokens_str.split(",") if t.strip()]
            else:
                single = os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip()
                tokens = [single] if single else []

            self._slots = [ApiKeySlot(token=token, index=i) for i, token in enumerate(tokens)]
            self._round_robin_index = 0
            self._initialized = True

            if self._slots:
                logger.info(
                    f"API key rotator initialized with {len(self._slots)} key(s): "
                    + ", ".join(s.masked for s in self._slots)
                )
            else:
                logger.warning("API key rotator: no keys found in environment")

    @property
    def key_count(self) -> int:
        """Total number of registered keys."""
        return len(self._slots)

    def get_active_key(self) -> ApiKeySlot | None:
        """Get the next available key using round-robin among non-cooled-down keys.

        Returns None if no keys are available (all in cooldown or no keys loaded).
        """
        with self._lock:
            if not self._slots:
                return None

            n = len(self._slots)
            # Try each key starting from current round-robin position
            for offset in range(n):
                idx = (self._round_robin_index + offset) % n
                slot = self._slots[idx]
                if slot.available:
                    self._round_robin_index = (idx + 1) % n
                    return slot

            # All keys in cooldown — return the one with shortest remaining cooldown
            best = min(self._slots, key=lambda s: s.cooldown_until)
            logger.warning(
                f"All {n} API keys in cooldown. Using key {best.masked} "
                f"(cooldown ends in {best.cooldown_remaining:.0f}s)"
            )
            return best

    def activate_key(self, slot: ApiKeySlot):
        """Set os.environ['ANTHROPIC_AUTH_TOKEN'] to the given key."""
        os.environ["ANTHROPIC_AUTH_TOKEN"] = slot.token
        # Also set ANTHROPIC_API_KEY for frontend SDK compatibility
        os.environ["ANTHROPIC_API_KEY"] = slot.token

    def report_rate_limit(self, slot: ApiKeySlot, retry_after: float | None = None):
        """Put a key on cooldown after a 429 error."""
        with self._lock:
            slot.consecutive_429s += 1
            slot.total_429s += 1

            if retry_after and retry_after > 0:
                cooldown = retry_after
            else:
                cooldown = _get_cooldown_seconds(slot.consecutive_429s)

            slot.cooldown_until = time.monotonic() + cooldown

            available_count = sum(1 for s in self._slots if s.available)
            logger.warning(
                f"API key {slot.masked} rate-limited (429 #{slot.consecutive_429s}). "
                f"Cooldown: {cooldown:.0f}s. "
                f"Available keys: {available_count}/{len(self._slots)}"
            )

    def report_success(self, slot: ApiKeySlot):
        """Record a successful API call — resets consecutive failure counter."""
        with self._lock:
            slot.consecutive_429s = 0
            slot.total_calls += 1

    def get_status(self) -> dict:
        """Get monitoring data for all keys."""
        with self._lock:
            keys = []
            for slot in self._slots:
                keys.append(
                    {
                        "key": slot.masked,
                        "available": slot.available,
                        "cooldown_remaining": round(slot.cooldown_remaining),
                        "consecutive_429s": slot.consecutive_429s,
                        "total_429s": slot.total_429s,
                        "total_calls": slot.total_calls,
                    }
                )

            available_count = sum(1 for s in self._slots if s.available)
            return {
                "total_keys": len(self._slots),
                "available_keys": available_count,
                "keys": keys,
            }


# Module-level singleton
_rotator: ApiKeyRotator | None = None
_rotator_lock = threading.Lock()


def get_api_key_rotator() -> ApiKeyRotator:
    """Get or create the global ApiKeyRotator singleton."""
    global _rotator
    if _rotator is None:
        with _rotator_lock:
            if _rotator is None:
                _rotator = ApiKeyRotator()
    return _rotator
