"""Rate limiting for Loom MCP server.

Token bucket per session/IP with configurable limits.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from threading import Lock
from typing import Optional


class TokenBucket:
    """Token bucket rate limiter."""

    def __init__(self, rate: float, capacity: int):
        self.rate = rate  # tokens per second
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.monotonic()
        self.lock = Lock()

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Returns True if allowed."""
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False


class RateLimiter:
    """Rate limiter with per-key token buckets."""

    def __init__(
        self,
        requests_per_minute: int = 60,
        burst_size: int = 10,
        enabled: bool = True,
    ):
        self.enabled = enabled
        self.rate = requests_per_minute / 60.0
        self.capacity = burst_size
        self.buckets: dict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket(self.rate, self.capacity)
        )
        self.lock = Lock()

    def allow(self, key: str = "default") -> bool:
        """Check if request is allowed for the given key."""
        if not self.enabled:
            return True

        with self.lock:
            bucket = self.buckets[key]
        return bucket.consume()

    def reset(self, key: Optional[str] = None) -> None:
        """Reset rate limiter state."""
        with self.lock:
            if key:
                self.buckets.pop(key, None)
            else:
                self.buckets.clear()


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter."""
    global _rate_limiter
    if _rate_limiter is None:
        enabled = os.environ.get("LOOM_RATE_LIMIT", "1") not in ("0", "false", "False", "")
        rpm = int(os.environ.get("LOOM_RPM", os.environ.get("LOOM_RATE_LIMIT", "60")))
        burst = int(os.environ.get("LOOM_BURST", "10"))
        _rate_limiter = RateLimiter(requests_per_minute=rpm, burst_size=burst, enabled=enabled)
    return _rate_limiter