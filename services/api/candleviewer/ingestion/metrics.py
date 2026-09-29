"""Prometheus metrics for `ClockGuard` (E08-S07 Observability section):
`exchange_clock_drift_ms`, `clock_offset_age_seconds`,
`clock_measurements_total{result}`, `clock_resync_triggered_total{reason}`.

Named to match the alert rules in `infra/prometheus/alerts/clock_sync.yml`
and SCR-147 (E42); kept adapter-agnostic (CONSTITUTION.md C-2.2 — this
module lives outside the concrete exchange adapter package and must not
reference exchange-specific nomenclature) even though only one exchange
adapter is wired up behind `exchange/base/` today.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge

exchange_clock_drift_ms = Gauge(
    "exchange_clock_drift_ms",
    "Last measured signed offset (server - local) to exchange server time, in milliseconds.",
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
