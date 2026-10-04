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

from candleviewer.observability.metrics import Counter, Gauge

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

# --- E08-S01-2: instrument catalogue refresh -------------------------------

instruments_refresh_total = Counter(
    "instruments_refresh_total",
    "Instrument catalogue refresh attempts, by result (ticket acceptance"
    " criterion 'Refresh fails').",
    ["result"],
)

instruments_cache_age_seconds = Gauge(
    "instruments_cache_age_seconds",
    "Seconds since the currently-served instrument catalogue snapshot was fetched.",
)

instruments_catalogue_size = Gauge(
    "instruments_catalogue_size",
    "Number of symbols in the currently-served instrument catalogue snapshot.",
)

# --- E08-S03: live ticker stream -------------------------------------------

ingest_events_total = Counter(
    "ingest_events_total",
    "Normalised market events ingested, by stream and symbol.",
    ["stream", "symbol"],
)

ws_topic_staleness_seconds = Gauge(
    "ws_topic_staleness_seconds",
    "Seconds since the last message on an upstream topic.",
    ["topic"],
)

ticker_merge_incomplete_total = Counter(
    "ticker_merge_incomplete_total",
    "Ticker deltas held because the merged state was not yet complete.",
    ["symbol"],
)

ingest_lag_seconds = Gauge(
    "ingest_lag_seconds",
    "Latest ingest lag (local ingest time minus exchange event time), by stream.",
    ["stream"],
)

ticker_writes_dropped_total = Counter(
    "ticker_writes_dropped_total",
    "Ticker rows dropped from the bounded write-behind queue (oldest first).",
)

# --- E08-S04: trade tape ----------------------------------------------------

trade_duplicates_suppressed_total = Counter(
    "trade_duplicates_suppressed_total",
    "Trade prints suppressed because their trade id was already ingested.",
    ["symbol"],
)

trade_gaps_total = Counter(
    "trade_gaps_total",
    "Tape gap windows recorded (reconnect), by whether backfill recovered them.",
    ["symbol", "recovered"],
)

trade_backfill_rows_total = Counter(
    "trade_backfill_rows_total",
    "Rows returned by the REST recent-trade gap backfill, by result.",
    ["result"],
)

trade_prints_rejected_total = Counter(
    "trade_prints_rejected_total",
    "Malformed/hostile trade frames rejected before the dedupe ring.",
)

questdb_write_queue_depth = Gauge(
    "questdb_write_queue_depth",
    "Rows waiting in a bounded QuestDB write-behind queue, by table.",
    ["table"],
)

trade_writes_dropped_total = Counter(
    "trade_writes_dropped_total",
    "Trade rows dropped from the bounded write-behind queue (oldest first).",
)

book_writes_dropped_total = Counter(
    "book_writes_dropped_total",
    "Order-book rows dropped from the bounded write-behind queue (oldest first).",
)
