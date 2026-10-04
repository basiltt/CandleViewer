"""Immutable MetricSnapshot with cross-rule memoisation (11.5 E2/E3/E7, 7.3)."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Protocol

from candleviewer.rules.ir.models import MetricRef

Value = Decimal | bool | str | None

DEFAULT_MAX_DATA_AGE_MS = 5_000
STALE_CADENCE_FACTOR = 3


@dataclass(frozen=True, slots=True)
class MetricValue:
    """One metric reading. ``value is None`` means unavailable; ``reason`` says why."""

    value: Value
    ts_ms: int
    cadence_ms: int = 0
    reason: str | None = None  # warmup | no_position | stale_data | ...

    def max_age_ms(self) -> int:
        return max(DEFAULT_MAX_DATA_AGE_MS, STALE_CADENCE_FACTOR * self.cadence_ms)


class MetricSource(Protocol):
    """Synchronous read of a memoised metric value (no await may interleave, E2)."""

    def read(self, ref: MetricRef) -> MetricValue: ...


def metric_key(ref: MetricRef) -> str:
    """Canonical, deterministic key for a metric reference (metric + params + scope)."""
    params = json.dumps(ref.params, sort_keys=True, separators=(",", ":"), default=str)
    return f"{ref.metric}{params}|{ref.symbol or ''}|{ref.account_id or ''}|{ref.timeframe or ''}"


@dataclass(frozen=True, slots=True)
class MetricSnapshot:
    taken_at_ms: int
    values: Mapping[str, MetricValue]

    def get(self, ref: MetricRef) -> MetricValue:
        return self.values[metric_key(ref)]

    def stale_keys(self) -> tuple[str, ...]:
        return tuple(
            k for k, v in self.values.items() if self.taken_at_ms - v.ts_ms > v.max_age_ms()
        )


class SnapshotBuilder:
    """Reads every referenced metric once; memoises across rules within one tick (7.3)."""

    def __init__(self, source: MetricSource) -> None:
        self._source = source
        self._cache: dict[str, MetricValue] = {}
        self.computations = 0
        self.cache_hits = 0

    def new_tick(self) -> None:
        """Invalidate the memo; call once per market update, not per rule."""
        self._cache.clear()

    def build(self, refs: Iterable[MetricRef], now_ms: int) -> MetricSnapshot:
        values: dict[str, MetricValue] = {}
        for ref in refs:
            key = metric_key(ref)
            if key in values:
                continue
            cached = self._cache.get(key)
            if cached is None:
                cached = self._source.read(ref)
                self._cache[key] = cached
                self.computations += 1
            else:
                self.cache_hits += 1
            values[key] = cached
        return MetricSnapshot(now_ms, MappingProxyType(values))
