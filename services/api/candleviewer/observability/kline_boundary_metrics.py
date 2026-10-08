"""`kline_hot_boundary_fallback_total` (#2060), defined in `observability` so both `storage`
(the boundary) and `bars.metrics` (which re-exports it onto the scraped registry) may import it."""

from __future__ import annotations

from candleviewer.observability.metrics import Counter

kline_hot_boundary_fallback_total = Counter(
    "kline_hot_boundary_fallback_total",
    "Klines hot boundary on the 90 d constant (reason: no_policy | invalid_policy | load_failed).",
    labelnames=("reason",),
)

__all__ = ["kline_hot_boundary_fallback_total"]
