"""Reconnect policy + connection-rate guard (E08-T04).

Full-jitter exponential backoff (0.5 s -> 30 s) and a sliding-window guard that
keeps connection opens below the per-IP limit (500 / 5 min; default headroom 480).
"""

from __future__ import annotations

import random
from collections import deque
from collections.abc import Callable


class ReconnectPolicy:
    def __init__(
        self, *, base_s: float = 0.5, cap_s: float = 30.0, rng: random.Random | None = None
    ) -> None:
        self._base = base_s
        self._cap = cap_s
        self._rng = rng or random.Random()  # noqa: S311  (jitter, not crypto)

    def next_delay(self, attempt: int) -> float:
        ceiling = min(self._cap, self._base * (2 ** min(max(attempt, 0), 32)))
        return self._rng.uniform(0, ceiling)


class ConnectionRateGuard:
    """Schedules opens so no window of `window_s` holds `>= limit` opens."""

    def __init__(
        self,
        clock: Callable[[], float],
        *,
        limit: int = 480,
        window_s: float = 300.0,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be positive")
        self._clock = clock
        self._limit = limit
        self._window = window_s
        self._opens: deque[float] = deque()

    def reserve(self) -> float:
        """Reserve one open slot; returns the delay (s) before it may be issued."""
        now = self._clock()
        start = now
        if len(self._opens) >= self._limit:
            start = max(now, self._opens[-self._limit] + self._window)
        self._opens.append(start)
        while len(self._opens) > self._limit:
            self._opens.popleft()
        return start - now

    def remaining(self) -> int:
        now = self._clock()
        used = sum(1 for t in self._opens if now - self._window < t <= now + self._window)
        return max(0, self._limit - used)
