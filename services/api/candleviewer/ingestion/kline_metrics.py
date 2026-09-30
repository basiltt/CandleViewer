"""Prometheus metrics for the E08-S06 kline backfill (Observability section):
`kline_backfill_pages_total{symbol,interval,result}`,
`kline_backfill_duration_seconds{symbol,interval}`,
`kline_cache_hit_ratio`, `kline_coverage_holes{symbol,interval}`.

Kept in its own module (rather than added to `ingestion/metrics.py`, which
is scoped to `ClockGuard`) so each ticket's metrics stay independently
reviewable/greppable, matching the one-concern-per-file convention already
used for `clock.py` vs `instruments.py` in this package.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

kline_backfill_pages_total = Counter(
    "kline_backfill_pages_total",
    "Kline backfill page fetch attempts, by result (ok, retry, error).",
    ["symbol", "interval", "result"],
)

kline_backfill_duration_seconds = Histogram(
    "kline_backfill_duration_seconds",
    "Wall-clock time to backfill one requested range, per (symbol, interval).",
    ["symbol", "interval"],
)

kline_cache_hit_ratio = Gauge(
    "kline_cache_hit_ratio",
    "Fraction of a requested kline range already covered by the local cache "
    "before any exchange fetch, per (symbol, interval).",
    ["symbol", "interval"],
)

kline_coverage_holes = Gauge(
    "kline_coverage_holes",
    "Remaining uncovered sub-ranges for a (symbol, interval) after the most "
    "recent backfill attempt.",
    ["symbol", "interval"],
)
