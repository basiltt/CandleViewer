"""Bars-module metrics (E12-T03) and their export onto the scraped `/metrics` registry.

Every name is declared `live` in `observability/metrics_catalogue.py` with `exported=True`:
the series are module-level (builders create children on the hot path, so they cannot use
the facade) and `export_bars_metrics()` re-exports them, with the `env` label, from the
library registry onto the app registry. `register_r0()` skips exported names, so nothing is
registered twice.
"""

from __future__ import annotations

from typing import Final

from candleviewer.observability.metrics import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ReexportCollector,
)

bar_builder_specs_in_use = Gauge(
    "bar_builder_specs_in_use", "Active bar specs per symbol.", labelnames=("symbol",)
)
bar_builder_fanout_latency_seconds = Histogram(
    "bar_builder_fanout_latency_seconds",
    "Time to fan one trade to every builder of its symbol.",
    buckets=(0.00001, 0.00005, 0.0001, 0.0005, 0.001, 0.005, 0.02),
)
bar_state_snapshots_written_total = Counter(
    "bar_state_snapshots_written_total", "Builder state blobs written."
)
bars_blob_discarded_total = Counter(
    "bars_blob_discarded_total",
    "State blobs discarded on restore.",
    labelnames=("reason",),
)
bar_builder_cold_starts_total = Counter(
    "bar_builder_cold_starts_total", "Specs started without a usable state blob."
)
bar_builder_cold_start_seconds = Histogram(
    "bar_builder_cold_start_seconds",
    "Restore + tape replay time before a spec goes live.",
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0),
)
bars_spec_cap_rejected_total = Counter(
    "bars_spec_cap_rejected_total",
    "Spec registrations refused by a cap.",
    labelnames=("reason",),
)
bar_builder_quarantined_total = Counter(
    "bar_builder_quarantined_total",
    "Series removed after their builder raised, or bars tasks that died.",
    labelnames=("reason",),
)
bar_emit_sink_errors_total = Counter(
    "bar_emit_sink_errors_total", "Bar emissions a sink failed to accept.", labelnames=("reason",)
)

#: Names served by `export_bars_metrics` (the S01/S02 builder counters plus the above).
EXPORTED_NAMES: Final[frozenset[str]] = frozenset(
    {
        "bars_built_total",
        "bars_amended_total",
        "bars_late_trade_dropped_total",
        "bar_volume_splits_total",
        "bars_partial_series_total",
        "bar_builder_specs_in_use",
        "bar_builder_fanout_latency_seconds",
        "bar_state_snapshots_written_total",
        "bars_blob_discarded_total",
        "bar_builder_cold_starts_total",
        "bar_builder_cold_start_seconds",
        "bars_spec_cap_rejected_total",
        "bar_emit_sink_errors_total",
        "bar_builder_quarantined_total",
    }
)


def export_bars_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve every bars series on `registry` (the scraped one) with a consistent `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})
