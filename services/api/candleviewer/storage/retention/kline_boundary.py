"""Policy-driven `/market/klines` hot/cold boundary (#2060, `21-database-schema.md` Sec.7).

The boundary is `now - hot_days(klines)` where `hot_days` comes from the DB-seeded
`RetentionPolicy`; with no policy loaded it falls back to the Sec.7 constant (90 d), logging once
at WARN and counting `kline_hot_boundary_fallback_total{reason=no_policy}`. Which source was used
is exposed via `source`/`hot_days` (debug log + health detail) — never in the public response.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Final

import structlog

from candleviewer.observability.metrics import Counter
from candleviewer.storage.models import StreamKind
from candleviewer.storage.retention.policy import RetentionPolicy

_log = structlog.get_logger(__name__)

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
    """Sync `boundary_us()` for `KlineReadService`; policy swapped in by `refresh`."""

    def __init__(
        self,
        policy: RetentionPolicy | None = None,
        *,
        clock_us: Callable[[], int] = lambda: time.time_ns() // 1000,
    ) -> None:
        self._policy = policy
        self._clock_us = clock_us
        self._warned = False
        self.source = SOURCE_FALLBACK

    def set_policy(self, policy: RetentionPolicy | None) -> None:
        self._policy = policy

    async def refresh(self, load: Callable[[], Awaitable[RetentionPolicy | None]]) -> None:
        """Load the policy once; a failing/absent source keeps the fallback (never raises)."""
        try:
            self._policy = await load()
        except Exception as exc:
            _log.warning("kline_hot_boundary_policy_load_failed", error=type(exc).__name__)
            self._policy = None

    @property
    def hot_days(self) -> int:
        rule = None if self._policy is None else self._policy.resolve("", StreamKind.KLINES)
        if rule is None:
            if not self._warned:
                self._warned = True
                _log.warning("kline_hot_boundary_no_policy_using_fallback", days=FALLBACK_HOT_DAYS)
            kline_hot_boundary_fallback_total.labels("no_policy").inc()
            self.source = SOURCE_FALLBACK
            return FALLBACK_HOT_DAYS
        self.source = SOURCE_POLICY
        return rule.hot_days

    def boundary_us(self) -> int:
        days = self.hot_days
        _log.debug("kline_hot_boundary", days=days, source=self.source)
        return self._clock_us() - days * US_PER_DAY

    def health_detail(self) -> str:
        return f"klines hot boundary: {self.source} ({self.hot_days} d)"
