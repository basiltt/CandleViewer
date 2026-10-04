"""Supervised alert maintenance loops (E40-T01): deliveries purge + gauge sampler.

Both are started by the ASGI lifespan only when `retention_enabled`
(`RetentionSchedule.alert_jobs()` non-empty). Interval-based like `RulePruneTask`;
idempotent, so the exact minute is immaterial. Tracked and cancellable (C-2.18).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from candleviewer.observability.context import spawn
from candleviewer.observability.metrics import BoundedMetric
from candleviewer.storage.retention.policy import ALERT_DELIVERIES_HOT_DAYS
from candleviewer.storage.retention.schedule import RetentionSchedule

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = 24 * 3600
GAUGE_INTERVAL_SECONDS = 15.0


class _Purger(Protocol):
    async def purge_expired(self, days: int) -> int: ...


class _GaugeSource(Protocol):
    async def gauges(self) -> dict[str, int]: ...


class _Loop:
    def __init__(
        self,
        name: str,
        enabled: bool,
        interval_s: float,
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        self._name = name
        self._enabled = enabled
        self._interval_s = interval_s
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def run_once(self) -> None:
        raise NotImplementedError

    async def _loop(self) -> None:
        while True:
            await self.run_once()
            await self._sleep(self._interval_s)

    def start(self) -> None:
        if self._enabled and self._task is None:
            self._task = spawn(self._loop(), name=self._name)

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class AlertDeliveriesPurgeTask(_Loop):
    def __init__(
        self,
        repo: _Purger,
        schedule: RetentionSchedule,
        *,
        interval_s: float = INTERVAL_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__("alert-deliveries-purge", bool(schedule.alert_jobs()), interval_s, sleep)
        self._repo = repo

    async def run_once(self) -> None:
        try:
            deleted = await self._repo.purge_expired(ALERT_DELIVERIES_HOT_DAYS)
            logger.info("alert_deliveries_purged", extra={"deleted": deleted})
        except Exception:
            logger.exception("alert_deliveries_purge_failed")


class AlertGaugeTask(_Loop):
    """Feeds `cv_alerts_total{enabled}` and `cv_alert_deliveries_pending`."""

    def __init__(
        self,
        repo: _GaugeSource,
        alerts_total: BoundedMetric,
        pending: BoundedMetric,
        *,
        enabled: bool = True,
        interval_s: float = GAUGE_INTERVAL_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__("alert-gauges", enabled, interval_s, sleep)
        self._repo = repo
        self._total = alerts_total
        self._pending = pending

    async def run_once(self) -> None:
        try:
            g = await self._repo.gauges()
        except Exception:
            logger.exception("alert_gauges_failed")
            return
        self._total.labels("true").set(g["cv_alerts_total{enabled=true}"])
        self._total.labels("false").set(g["cv_alerts_total{enabled=false}"])
        self._pending.child().set(g["cv_alert_deliveries_pending"])
