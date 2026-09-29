"""Prometheus metrics for the `exchange.bybit` REST client (E08-T02
Observability section): `bybit_rest_requests_total`,
`bybit_rest_latency_seconds`, `bybit_rate_limit_remaining`,
`bybit_rate_limited_total`.

`exchange_errors_total` is **not** redefined here — it is already owned by
`exchange/base/boundary.py` (E08-T01) and this client uses that module's
`translate_exchange_error` so the metric stays a single Prometheus series
across every adapter, not a per-adapter duplicate.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

bybit_rest_requests_total = Counter(
    "bybit_rest_requests_total",
    "Bybit REST requests, by endpoint and result.",
    ["endpoint", "result"],
)

bybit_rest_latency_seconds = Histogram(
    "bybit_rest_latency_seconds",
    "Bybit REST request latency, by endpoint.",
    ["endpoint"],
)

bybit_rate_limit_remaining = Gauge(
    "bybit_rate_limit_remaining",
    "Last-observed remaining rate-limit budget, by UID and endpoint class.",
    ["uid", "endpoint_class"],
)

bybit_rate_limited_total = Counter(
    "bybit_rate_limited_total",
    "Requests that hit a rate-limit retCode, by code.",
    ["code"],
)
