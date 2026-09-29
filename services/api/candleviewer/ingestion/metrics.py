"""Prometheus metrics for `ClockGuard` (E08-S07 Observability section):
`bybit_clock_drift_ms`, `clock_offset_age_seconds`,
`clock_measurements_total{result}`, `clock_resync_triggered_total{reason}`.

Named exactly as the ticket body's Observability section so the alert rules
in `infra/prometheus/alerts/clock_sync.yml` and SCR-147 (E42) can reference
them verbatim.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge

bybit_clock_drift_ms = Gauge(
    "bybit_clock_drift_ms",
    "Last measured signed offset (server - local) to Bybit server time, in milliseconds.",
)

clock_offset_age_seconds = Gauge(
    "clock_offset_age_seconds",
    "Seconds since the last successful clock offset measurement.",
)

clock_measurements_total = Counter(
    "clock_measurements_total",
    "Clock offset measurement attempts, by result.",
    ["result"],
)

clock_resync_triggered_total = Counter(
    "clock_resync_triggered_total",
    "Immediate clock resyncs triggered outside the periodic schedule, by reason.",
    ["reason"],
)
