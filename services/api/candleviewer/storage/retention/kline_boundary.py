"""Policy-driven `/market/klines` hot/cold boundary (#2060, `21-database-schema.md` Sec.7).

The boundary is `now - hot_days(klines)` where `hot_days` comes from the DB-seeded
`RetentionPolicy`; with no policy loaded it falls back to the Sec.7 constant (90 d), logging once
at WARN and counting `kline_hot_boundary_fallback_total{reason=no_policy}`. Which source was used
is exposed via `source`/`hot_days` (debug log + health detail) — never in the public response.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Final

import structlog

from candleviewer.observability.context import spawn
from candleviewer.observability.metrics import Counter
from candleviewer.storage.models import StreamKind
from candleviewer.storage.retention.policy import RetentionPolicy


def _log() -> Any:
    return structlog.get_logger(__name__)


FALLBACK_HOT_DAYS: Final = 90
US_PER_DAY: Final = 86_400 * 1_000_000
SOURCE_POLICY: Final = "policy"
SOURCE_FALLBACK: Final = "fallback"

kline_hot_boundary_fallback_total = Counter(
    "kline_hot_boundary_fallback_total",
    "Klines hot boundary computed from the constant because no retention policy is loaded.",
    ["reason"],
)


class KlineHotBoundary:
    """Sync `boundary_us()` for `KlineReadService`; the policy is swapped in by `refresh`."""

    def __init__(
        self,
        policy: RetentionPolicy | None = None,
        *,
        clock_us: Callable[[], int] = lambda: time.time_ns() // 1000,
    ) -> None:
        self._clock_us = clock_us
        self._failing = False
        self.hot_days = FALLBACK_HOT_DAYS
        self.source = SOURCE_FALLBACK
        self._apply(policy)

    def _apply(self, policy: RetentionPolicy | None) -> None:
        """The single compute site: resolve days/source; count + warn on fallback transitions."""
        rule = None if policy is None else policy.resolve("", StreamKind.KLINES)
        if rule is None:
            if self.source == SOURCE_POLICY or not self._failing:
                _log().warning(
                    "kline_hot_boundary_no_policy_using_fallback", days=FALLBACK_HOT_DAYS
                )
            self._failing = True
            kline_hot_boundary_fallback_total.labels("no_policy").inc()
            self.hot_days, self.source = FALLBACK_HOT_DAYS, SOURCE_FALLBACK
            return
        self._failing = False
        self.hot_days, self.source = rule.hot_days, SOURCE_POLICY

    async def refresh(self, load: Callable[[], Awaitable[RetentionPolicy | None]]) -> None:
        """Reload the policy. A failing load keeps the last value (WARN once per transition)."""
        try:
            policy = await load()
        except Exception as exc:
            if not self._failing:
                _log().warning("kline_hot_boundary_policy_load_failed", error=type(exc).__name__)
            self._failing = True
            return
        self._apply(policy)

    def boundary_us(self) -> int:
        return self._clock_us() - self.hot_days * US_PER_DAY

    def health_detail(self) -> str:
        return f"klines hot boundary: {self.source} ({self.hot_days} d)"


class KlineBoundaryRefreshTask:
    """Tracked periodic reload (retention rules are editable); cancelled on shutdown."""

    def __init__(
        self,
        boundary: KlineHotBoundary,
        load: Callable[[], Awaitable[RetentionPolicy | None]],
        interval_s: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._b, self._load, self._interval_s, self._sleep = boundary, load, interval_s, sleep
        self._task: asyncio.Task[None] | None = None

    async def _loop(self) -> None:
        while True:
            await self._sleep(self._interval_s)
            await self.load_now()

    async def load_now(self) -> None:
        await self._b.refresh(self._load)

    def start(self) -> None:
        if self._task is None:
            self._task = spawn(self._loop(), name="kline-hot-boundary-refresh")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
