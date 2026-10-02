"""Cold-tier metrics and the `system_events` sink (E07-T04 "Observability").

`system_events` rows are written by whoever owns that table; until it is
wired, `LoggingSystemEventSink` emits a structured CRITICAL log line that
the alerting pipeline already scrapes. Log payloads carry only paths
*relative to* `CV_COLD_ROOT` — never absolute paths, DSNs or credentials.
"""

from __future__ import annotations

from typing import Literal, Protocol

import structlog

from candleviewer.observability.metrics import Counter, Gauge, Histogram

Severity = Literal["INFO", "WARNING", "CRITICAL"]

storage_export_rows_total = Counter(
    "storage_export_rows_total", "Rows exported hot->cold.", ["stream", "result"]
)
storage_export_bytes_total = Counter(
    "storage_export_bytes_total", "Parquet bytes written by the exporter.", ["stream"]
)
storage_export_duration_seconds = Histogram(
    "storage_export_duration_seconds", "Wall time of one partition export.", ["stream"]
)
storage_export_verify_failures_total = Counter(
    "storage_export_verify_failures_total", "Exports aborted on row-count/checksum mismatch."
)
storage_compaction_files_merged_total = Counter(
    "storage_compaction_files_merged_total", "Parquet files merged away by the compactor."
)
storage_cold_bytes = Gauge("storage_cold_bytes", "Bytes in the cold tier.", ["stream"])
storage_scrub_mismatches_total = Counter(
    "storage_scrub_mismatches_total", "Files quarantined after a checksum/row-count mismatch."
)
storage_scrub_last_run_timestamp_seconds = Gauge(
    "storage_scrub_last_run_timestamp_seconds",
    "Unix time the last full cold-tier scrub finished (SR-094 observability).",
)


class SystemEventSink(Protocol):
    """Destination for `system_events` rows (CRITICAL on verify failure and
    quarantine, per `21-database-schema.md` Sec.5.3)."""

    async def emit(self, severity: Severity, code: str, detail: dict[str, str | int]) -> None: ...


class LoggingSystemEventSink:
    """Default sink: a structured log record at the matching level.

    Resolves a fresh `structlog` logger on every call rather than caching one
    at import time: a module-level logger created before a test calls
    `configure_logging()` (or after `structlog.reset_defaults()`) can be
    bound to a stale processor chain under `cache_logger_on_first_use=True`,
    silently dropping output. Re-resolving is cheap (`structlog` memoises the
    underlying logger factory itself) and keeps this sink honest about
    whatever configuration is active `at emit time`.
    """

    async def emit(self, severity: Severity, code: str, detail: dict[str, str | int]) -> None:
        logger = structlog.get_logger(__name__)
        if severity == "CRITICAL":
            logger.critical("system_event", code=code, **detail)
        elif severity == "WARNING":
            logger.warning("system_event", code=code, **detail)
        else:
            logger.info("system_event", code=code, **detail)
