"""Supervised alert maintenance loops (E40-T01): deliveries purge + gauge sampler.

Both are started by the ASGI lifespan only when `retention_enabled`
(`RetentionSchedule.alert_jobs()` non-empty). Interval-based like `RulePruneTask`;
idempotent, so the exact minute is immaterial. Tracked and cancellable (C-2.18).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Protocol

import pyarrow as pa
import pyarrow.parquet as pq

from candleviewer.observability.context import spawn
from candleviewer.observability.metrics import BoundedMetric
from candleviewer.storage.retention.policy import ALERT_DELIVERIES_HOT_DAYS
from candleviewer.storage.retention.schedule import RetentionSchedule

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = 24 * 3600
GAUGE_INTERVAL_SECONDS = 15.0
ALERT_DELIVERIES_DATASET = "alert_deliveries"
PURGE_BATCH = 5000


class _Purger(Protocol):
    async def fetch_expired(self, days: int, limit: int = ...) -> Sequence[Any]: ...

    async def delete_ids(self, ids: list[int]) -> int: ...


def archive_rows(root: Path, rows: Sequence[Any]) -> list[Path]:
    """Write rows to hive-partitioned Parquet (`alert_deliveries/dt=YYYY-MM-DD/`).

    Atomic (tmp file + `os.replace`) and fsynced so the caller may delete the
    source rows only after this returns (archive_parquet, schema doc retention table).
    """
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        d = asdict(r) if is_dataclass(r) and not isinstance(r, type) else dict(r)
        d["context"] = json.dumps(d.get("context"), sort_keys=True, default=str)
        by_day[d["queued_at"].strftime("%Y-%m-%d")].append(d)
    out: list[Path] = []
    for day, items in sorted(by_day.items()):
        part = root / ALERT_DELIVERIES_DATASET / f"dt={day}"
        part.mkdir(parents=True, exist_ok=True)
        final = part / f"part-{uuid.uuid4().hex}.parquet"
        tmp = final.with_suffix(".tmp")
        pq.write_table(pa.Table.from_pylist(items), tmp, compression="zstd")
        with tmp.open("r+b") as fh:
            os.fsync(fh.fileno())
        os.replace(tmp, final)
        out.append(final)
    return out


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
        archive_root: Path,
        has_owner_dsn: bool = True,
        interval_s: float = INTERVAL_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        # Without a cv_owner connection every DELETE is refused by trg_ad_append,
        # so the loop stays off (and says so) instead of failing silently forever.
        enabled = bool(schedule.alert_jobs()) and has_owner_dsn
        if bool(schedule.alert_jobs()) and not has_owner_dsn:
            logger.warning("alert_deliveries_purge_disabled_no_owner_dsn")
        super().__init__("alert-deliveries-purge", enabled, interval_s, sleep)
        self._repo = repo
        self._root = archive_root

    async def run_once(self) -> None:
        try:
            total = 0
            while True:
                rows = await self._repo.fetch_expired(ALERT_DELIVERIES_HOT_DAYS, PURGE_BATCH)
                if not rows:
                    break
                # Archive first; delete only after the Parquet files are durable.
                await asyncio.to_thread(archive_rows, self._root, rows)
                total += await self._repo.delete_ids([r.id for r in rows])
                if len(rows) < PURGE_BATCH:
                    break
            logger.info("alert_deliveries_archived_and_purged", extra={"deleted": total})
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
