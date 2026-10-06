"""Bounded, retrying hot-tier write-behind buffer (#1918, E08-Q03 chaos scenario 11).

Shared by `TradeStream` and `BookStream`. Rules:

* **Never blocks the reader** — `put` is sync; a full buffer evicts the oldest
  row (drop-oldest, C-2.18), counted in `*_writes_dropped_total{reason}`:
  `outage` while the writer is failing, else `queue_full`.
* **A failed batch is never discarded** — `requeue` puts it back at the head
  (order kept), then `backoff()` sleeps an exponential, jittered delay
  (injected sleep/rand; no real sleeps in tests). Rows leave only by a
  successful write or by eviction.
* **Lost rows are never hidden** — every evicted row's `(symbol, ts_us)` is
  merged into a per-symbol `CoverageIndex` of *lost* hot-tier ranges, so the
  recorder/backfill can heal them; `degraded` feeds the
  `hot_tier_write_behind` health component (degraded, not fatal).

Plain code on the hot path (C-2.20); single consumer (the write loop).
"""

from __future__ import annotations

import asyncio
import random
from collections import deque
from collections.abc import Awaitable, Callable, Iterable

from candleviewer.ingestion.kline_coverage import CoverageIndex, Range
from candleviewer.ingestion.metrics import questdb_write_queue_depth
from candleviewer.observability.metrics import Counter

BACKOFF_BASE_S = 0.1
BACKOFF_CAP_S = 10.0
_JITTER = random.SystemRandom().random


class WriteBehindBuffer[T]:
    def __init__(
        self,
        *,
        table: str,
        maxsize: int,
        dropped: Counter,
        key: Callable[[T], tuple[str, int]],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rand: Callable[[], float] | None = None,
        base_s: float = BACKOFF_BASE_S,
        cap_s: float = BACKOFF_CAP_S,
    ) -> None:
        self._table, self._max, self._dropped, self._key = table, maxsize, dropped, key
        self._sleep, self._base, self._cap = sleep, base_s, cap_s
        self._rand = rand if rand is not None else _JITTER
        self._rows: deque[T] = deque()
        self._nonempty = asyncio.Event()
        self._lost: dict[str, CoverageIndex] = {}
        self.failures = 0  # consecutive failed writes; 0 = healthy
        self.evicted = 0

    def qsize(self) -> int:
        return len(self._rows)

    def full(self) -> bool:
        return len(self._rows) >= self._max

    @property
    def degraded(self) -> bool:
        return self.failures > 0

    def lost_ranges(self, symbol: str) -> list[Range]:
        idx = self._lost.get(symbol)
        return [] if idx is None else idx.covered_ranges()

    def _evict_oldest(self) -> None:
        row = self._rows.popleft()
        self.evicted += 1
        self._dropped.labels(reason="outage" if self.degraded else "queue_full").inc()
        sym, ts_us = self._key(row)
        self._lost.setdefault(sym, CoverageIndex()).mark_covered(Range(ts_us, ts_us + 1))

    def _gauge(self) -> None:
        questdb_write_queue_depth.labels(table=self._table).set(len(self._rows))

    def put(self, row: T) -> None:
        if self.full():
            self._evict_oldest()
        self._rows.append(row)
        self._nonempty.set()
        self._gauge()

    async def take(self, max_batch: int) -> list[T]:
        """Wait for a row, then pop up to `max_batch` oldest-first."""
        while not self._rows:
            self._nonempty.clear()
            await self._nonempty.wait()
        n = min(max_batch, len(self._rows))
        batch = [self._rows.popleft() for _ in range(n)]
        self._gauge()
        return batch

    def requeue(self, rows: Iterable[T]) -> None:
        """Put unwritten rows back at the head (order kept); overflow evicts oldest."""
        self.failures += 1
        self._rows.extendleft(reversed(list(rows)))
        while len(self._rows) > self._max:
            self._evict_oldest()
        if self._rows:
            self._nonempty.set()
        self._gauge()

    def delay_s(self) -> float:
        """Backoff for the current failure streak: base*2^(n-1), capped, x[1, 1.25)."""
        step = min(self._cap, self._base * 2.0 ** max(0, self.failures - 1))
        return step * (1.0 + 0.25 * self._rand())

    async def backoff(self) -> None:
        await self._sleep(self.delay_s())

    def succeeded(self) -> None:
        self.failures = 0


__all__ = ["BACKOFF_BASE_S", "BACKOFF_CAP_S", "WriteBehindBuffer"]
