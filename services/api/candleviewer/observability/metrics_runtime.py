"""Background metric tasks (E04-T03): loop-lag sampler, cardinality check, fallback snapshot.

All three are plain coroutines the caller owns (TaskGroup / supervisor, C-2.18);
each takes an injected `sleep` so tests drive them deterministically.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Final

import structlog

from candleviewer.observability.metrics import BoundedMetric, Metrics
from candleviewer.observability.metrics_catalogue import SNAPSHOT_KEYS

#: 100 ms cadence: a 1 s cadence would make a 100 ms alert measure its own error.
LOOP_LAG_INTERVAL_S: Final = 0.1
CARDINALITY_CHECK_INTERVAL_S: Final = 60.0
FALLBACK_SNAPSHOT_INTERVAL_S: Final = 300.0

Sleep = Callable[[float], Awaitable[None]]

_log = structlog.get_logger("candleviewer.observability.metrics")


async def run_loop_lag_sampler(
    histogram: BoundedMetric,
    clock: Callable[[], float],
    *,
    interval: float = LOOP_LAG_INTERVAL_S,
    sleep: Sleep = asyncio.sleep,
    iterations: int | None = None,
) -> None:
    """Sleep `interval`, record the overshoot. `iterations=None` runs forever."""
    child = histogram.child()
    n = 0
    while iterations is None or n < iterations:
        start = clock()
        await sleep(interval)
        child.observe(max(0.0, clock() - start - interval))
        n += 1


async def run_cardinality_check(
    metrics: Metrics,
    *,
    interval: float = CARDINALITY_CHECK_INTERVAL_S,
    sleep: Sleep = asyncio.sleep,
    iterations: int | None = None,
) -> None:
    """Every 60 s, log the metrics that sit at their `max_series` bound."""
    n = 0
    while iterations is None or n < iterations:
        await sleep(interval)
        breached = metrics.check_cardinality()
        if breached:
            _log.error("metric_cardinality_at_bound", metrics=breached)
        n += 1


def write_fallback_snapshot(metrics: Metrics) -> dict[str, float]:
    """Write one compact snapshot of the key gauges to the structured log."""
    snap = metrics.snapshot(SNAPSHOT_KEYS)
    _log.info("metrics_fallback_snapshot", env=metrics.env, metrics=snap)
    return snap


async def run_fallback_snapshots(
    metrics: Metrics,
    *,
    interval: float = FALLBACK_SNAPSHOT_INTERVAL_S,
    sleep: Sleep = asyncio.sleep,
    iterations: int | None = None,
) -> None:
    """Scrape-failure fallback: a Prometheus outage still leaves a log trail."""
    n = 0
    while iterations is None or n < iterations:
        await sleep(interval)
        write_fallback_snapshot(metrics)
        n += 1
