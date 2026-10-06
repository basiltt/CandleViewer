"""Virtual time for the E08-Q03 chaos suite (C-13.7: no wall-clock sleeps).

`VirtualClock.sleep` parks the caller on a timer heap; nothing moves until the
test calls `advance()` / `run_until()`, which first lets the event loop reach
quiescence (the harness-side barrier the ticket asks for), then fires timers
strictly in deadline order. Same seed + same script => same interleaving.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
from collections.abc import Callable

#: Corpus epoch (packages/fixtures/bybit/2026-10-05: first envelope `ts`).
EPOCH_S = 1_700_000_000.0
_SETTLE_SPINS = 64


class ScenarioTimeoutError(AssertionError):
    """A predicate did not become true inside its declared recovery SLO."""


class VirtualClock:
    def __init__(self, *, start_s: float = 0.0) -> None:
        self.now = start_s
        self._timers: list[tuple[float, int, asyncio.Future[None]]] = []
        self._seq = itertools.count()

    def __call__(self) -> float:
        """Monotonic seconds (scenario-relative)."""
        return self.now

    def wall_s(self) -> float:
        return EPOCH_S + self.now

    def now_us(self) -> int:
        return round(self.wall_s() * 1_000_000)

    async def sleep(self, seconds: float) -> None:
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        heapq.heappush(self._timers, (self.now + max(0.0, seconds), next(self._seq), fut))
        await fut

    async def settle(self) -> None:
        """Quiescence barrier: run every ready callback chain to completion."""
        for _ in range(_SETTLE_SPINS):
            await asyncio.sleep(0)

    def _next_deadline(self) -> float | None:
        while self._timers and self._timers[0][2].done():  # cancelled sleepers
            heapq.heappop(self._timers)
        return self._timers[0][0] if self._timers else None

    async def _fire_next(self) -> None:
        deadline, _, fut = heapq.heappop(self._timers)
        self.now = max(self.now, deadline)
        fut.set_result(None)
        await self.settle()

    async def advance(self, seconds: float) -> None:
        target = self.now + seconds
        await self.settle()
        while (nxt := self._next_deadline()) is not None and nxt <= target:
            await self._fire_next()
        self.now = target
        await self.settle()

    async def run_until(self, pred: Callable[[], bool], *, within_s: float, what: str) -> float:
        """Advance timer-by-timer until `pred()`; returns elapsed virtual seconds.

        Exceeding `within_s` fails the scenario: recovery SLOs are assertions."""
        start = self.now
        await self.settle()
        while not pred():
            nxt = self._next_deadline()
            if nxt is None or nxt > start + within_s:
                raise ScenarioTimeoutError(f"{what}: not reached within {within_s}s (SLO)")
            await self._fire_next()
        return self.now - start
