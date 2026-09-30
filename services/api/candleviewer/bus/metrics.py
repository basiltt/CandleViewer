"""Prometheus metrics for the bus module (M5), per E08-T03's Observability
section: `bus_published_total`, `bus_delivered_total`, `bus_conflated_total`,
`ingest_queue_full_total`, `bus_subscriber_lag`, `bus_stream_invalidated_total`.
"""

from __future__ import annotations

from candleviewer.observability.metrics import Counter, Gauge

bus_published_total = Counter(
    "bus_published_total",
    "Events published to the bus, by topic class.",
    ["topic_class"],
)

bus_delivered_total = Counter(
    "bus_delivered_total",
    "Events delivered to a subscriber queue.",
    ["subscriber"],
)

bus_conflated_total = Counter(
    "bus_conflated_total",
    "Events superseded by a newer event under CONFLATE_LATEST before delivery.",
    ["topic_class"],
)

ingest_queue_full_total = Counter(
    "ingest_queue_full_total",
    "Times a NEVER_DROP subscriber queue was observed full and publish awaited.",
    ["class"],
)

bus_subscriber_lag = Gauge(
    "bus_subscriber_lag",
    "Current queue depth (high-water tracked) for a subscriber.",
    ["subscriber"],
)

bus_stream_invalidated_total = Counter(
    "bus_stream_invalidated_total",
    "INVALIDATE_ON_FULL subscriptions that received a StreamInvalidated marker.",
    ["topic_class"],
)
