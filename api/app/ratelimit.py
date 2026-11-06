"""Small in-memory sliding-window rate limiter (single-process deployment, see ADR-004).

Used for login attempts (brute-force protection) and chat requests. M5 adds per-session budgets.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, now: float | None = None) -> bool:
        """Record an attempt; False if `key` already used its allowance in the window."""
        current = time.monotonic() if now is None else now
        hits = self._hits[key]
        while hits and current - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(current)
        if len(self._hits) > 10_000:  # bound memory under key-spraying
            self._prune(current)
        return True

    def retry_after(self, key: str, *, now: float | None = None) -> int:
        current = time.monotonic() if now is None else now
        hits = self._hits.get(key)
        if not hits:
            return 0
        return max(1, int(self.window - (current - hits[0])) + 1)

    def _prune(self, current: float) -> None:
        for key in [k for k, h in self._hits.items() if not h or current - h[-1] >= self.window]:
            del self._hits[key]
