"""Prometheus metrics for the bus module (M5), per E08-T03's Observability
section. Names/labels/help are declared in the ingestion metric registry
(`candleviewer/ingestion/metrics.py` `SPECS`, E08-T06) and instantiated here
because `bus` may not import `ingestion` (`.importlinter` M5).
"""

from __future__ import annotations

from candleviewer.observability.metrics import Counter, Gauge

bus_published_total = Counter(
    "bus_published_total",
    "Events published, by topic class.",
    ["topic_class"],
)

bus_delivered_total = Counter(
    "bus_delivered_total",
    "Events delivered to a subscriber.",
    ["subscriber"],
)

bus_conflated_total = Counter(
    "bus_conflated_total",
    "Events superseded under CONFLATE_LATEST.",
    ["topic_class"],
)

ingest_queue_full_total = Counter(
    "ingest_queue_full_total",
    "NEVER_DROP queue observed full.",
    ["class"],
)

bus_subscriber_lag = Gauge(
    "bus_subscriber_lag",
    "Current queue depth per subscriber.",
    ["subscriber"],
)

bus_stream_invalidated_total = Counter(
    "bus_stream_invalidated_total",
    "INVALIDATE_ON_FULL markers delivered.",
    ["topic_class"],
)
