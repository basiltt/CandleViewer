"""`source_tier=auto` query router (E07-T05, `21-database-schema.md` Sec.5.5).

Boundary maths: the hot window holds `ts >= boundary` where
`boundary = now_us - hot_retention_us(stream)`. `TimeRange` is
start-inclusive / end-exclusive, so a range is *entirely hot* iff
`start >= boundary` and *entirely cold* iff `end <= boundary`; anything else
straddles and is merged (hot wins ties — freshest after a dedup upsert).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import structlog

from candleviewer.observability.metrics import Counter
from candleviewer.storage.models import StreamKind, TierHint, TimeRange
from candleviewer.storage.natural_keys import NATURAL_KEY

ServedBy = Literal["hot", "cold", "both"]
Reader = Callable[[str, TimeRange], Awaitable[Sequence[Any]]]

storage_router_queries_total = Counter(
    "storage_router_queries_total", "Router reads by serving tier.", ["tier"]
)
storage_router_merge_rows_total = Counter(
    "storage_router_merge_rows_total", "Rows emitted by straddle merges."
)

storage_router_dedup_conflicts_total = Counter(
    "storage_router_dedup_conflicts_total",
    "Straddle-merge natural-key collisions whose non-key fields differ.",
)


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


_US_PER_DAY = 86_400_000_000


@dataclass(frozen=True, slots=True)
class RoutedRows:
    """Rows plus which tier(s) served them (the OpenAPI read contract)."""

    rows: list[Any]
    tier: ServedBy

    @property
    def sources(self) -> list[str]:
        """`meta.sources` (22-api-openapi.yaml `DataMeta`): the tiers in this response."""
        return {"hot": ["questdb"], "cold": ["parquet"], "both": ["questdb", "parquet"]}[self.tier]


def _field(row: Any, name: str) -> Any:
    if isinstance(row, Mapping):
        if name in row:
            return row[name]
        if name == "ts" and "ts_us" in row:
            return row["ts_us"]
        raise KeyError(name)
    if hasattr(row, name):
        return getattr(row, name)
    if name == "ts":
        return row.ts_us
    raise AttributeError(name)


def _as_fields(row: Any) -> dict[str, Any]:
    return dict(row) if isinstance(row, Mapping) else dict(vars(row))


def _differing_fields(cold: Any, hot: Any, key: tuple[str, ...]) -> list[str]:
    a, b = _as_fields(cold), _as_fields(hot)
    return sorted(f for f in a.keys() | b.keys() if f not in key and a.get(f) != b.get(f))


def dedup_merge(
    cold_rows: Sequence[Any], hot_rows: Sequence[Any], key: tuple[str, ...]
) -> list[Any]:
    """Merge by `ts` (ascending), dedup on `key`; the hot row wins ties."""
    merged: dict[tuple[Any, ...], Any] = {}
    for row in cold_rows:
        merged[tuple(_field(row, k) for k in key)] = row
    for row in hot_rows:  # inserted last => overrides the cold twin
        k = tuple(_field(row, name) for name in key)
        prior = merged.get(k)
        if prior is not None:
            diff = _differing_fields(prior, row, key)
            if diff:  # hot wins, but never silently (field names only, no values)
                storage_router_dedup_conflicts_total.inc()
                logger().warning("storage_router_dedup_conflict", key=list(key), fields=diff)
        merged[k] = row
    return sorted(merged.values(), key=lambda r: _field(r, "ts"))


class TierRouter:
    """Resolves `hot | cold | auto` and merges once, here (never at call sites)."""

    def __init__(
        self,
        hot: Mapping[StreamKind, Reader],
        cold: Mapping[StreamKind, Reader],
        hot_retention_days: Callable[[StreamKind], int],
        *,
        clock_us: Callable[[], int] = lambda: time.time_ns() // 1000,
        accelerated: Callable[[], bool] = lambda: False,
    ) -> None:
        self._hot = hot
        self._cold = cold
        self._hot_days = hot_retention_days
        self._clock_us = clock_us
        self._accelerated = accelerated
        # Monotonic guard: data older than a boundary may already be dropped from
        # hot, so the boundary never moves backwards (clock step-back, recovery
        # from accelerated mode).
        self._high_water: dict[StreamKind, int] = {}

    def boundary_us(self, stream: StreamKind) -> int:
        # Accelerated reaper mode halves the effective hot window (SR-096).
        window = self._hot_days(stream) * _US_PER_DAY
        if self._accelerated():
            window //= 2
        boundary = max(self._clock_us() - window, self._high_water.get(stream, 0))
        self._high_water[stream] = boundary
        return boundary

    def resolve(self, stream: StreamKind, rng: TimeRange, tier: TierHint = "auto") -> ServedBy:
        if tier == "hot":
            return "hot"
        if tier == "cold":
            return "cold"
        boundary = self.boundary_us(stream)
        if rng.start_us >= boundary:
            return "hot"
        if rng.end_us <= boundary:
            return "cold"
        return "both"

    async def read(
        self, stream: StreamKind, sym: str, rng: TimeRange, tier: TierHint = "auto"
    ) -> RoutedRows:
        served = self.resolve(stream, rng, tier)
        storage_router_queries_total.labels(tier=served).inc()
        if served == "hot":
            return RoutedRows(list(await self._hot[stream](sym, rng)), "hot")
        if served == "cold":
            return RoutedRows(list(await self._cold[stream](sym, rng)), "cold")
        hot_rows, cold_rows = await asyncio.gather(
            self._hot[stream](sym, rng), self._cold[stream](sym, rng)
        )
        rows = dedup_merge(cold_rows, hot_rows, NATURAL_KEY[stream])
        storage_router_merge_rows_total.inc(len(rows))
        return RoutedRows(rows, "both")
