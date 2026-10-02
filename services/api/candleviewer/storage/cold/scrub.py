"""Checksum scrub (SR-094): verify on read and in the weekly scrub.

A file whose SHA-256 or row count no longer matches its manifest entry is
quarantined (moved out of the dataset tree and dropped from the manifest,
so no DuckDB view or `query()` can read it), a CRITICAL `system_events` row
is emitted and `storage_scrub_mismatches_total` is incremented. The caller
then receives `StorageExportVerifyFailed` — the Protocol's contract.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pyarrow.parquet as pq
import structlog

from candleviewer.storage.cold.layout import ColdPaths, DatasetRegistry, stream_dir_name
from candleviewer.storage.cold.manifest import ManifestStore, sha256_of
from candleviewer.storage.cold.observability import (
    SystemEventSink,
    storage_scrub_last_run_timestamp_seconds,
    storage_scrub_mismatches_total,
)
from candleviewer.storage.errors import StorageExportVerifyFailed
from candleviewer.storage.models import StreamKind

logger = structlog.get_logger(__name__)


def _first_mismatch(paths: ColdPaths) -> tuple[str, str] | None:
    """Blocking: returns `(file, reason)` for the first bad entry, else None."""
    store = ManifestStore(paths.manifests_dir)
    for entry in store.read(paths.partition_dir, paths.root):
        file_path = paths.partition_dir / entry.file
        if not file_path.is_file():
            return entry.file, "missing"
        if sha256_of(file_path) != entry.sha256:
            return entry.file, "sha256"
        try:
            rows = pq.ParquetFile(file_path).metadata.num_rows
        except Exception:
            return entry.file, "unreadable"
        if rows != entry.row_count:
            return entry.file, "row_count"
    return None


async def verify_partition(paths: ColdPaths, events: SystemEventSink) -> bool:
    """Verify every manifest entry of one partition; quarantine + alert and
    raise `StorageExportVerifyFailed` on the first mismatch."""
    bad = await asyncio.to_thread(_first_mismatch, paths)
    if bad is None:
        return True
    file_name, reason = bad
    store = ManifestStore(paths.manifests_dir)
    rel_dir = paths.partition_dir.relative_to(paths.root).as_posix()
    quarantined = await asyncio.shield(
        asyncio.to_thread(store.quarantine, paths.partition_dir, paths.root, file_name)
    )
    storage_scrub_mismatches_total.inc()
    await events.emit(
        "CRITICAL",
        "STORAGE_COLD_FILE_QUARANTINED",
        {
            "partition": rel_dir,
            "file": file_name,
            "reason": reason,
            "quarantine": quarantined.as_posix(),
        },
    )
    raise StorageExportVerifyFailed(f"{rel_dir}/{file_name}: {reason} mismatch; quarantined")


SCRUB_INTERVAL_SECONDS = 7 * 24 * 3600


async def scrub_all(
    registry: DatasetRegistry,
    events: SystemEventSink,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Weekly scrub (SR-094): verify every manifested partition of every
    registered stream/symbol. Mismatches are quarantined + alerted by
    `verify_partition`; the sweep continues. Stamps the last-run gauge when
    done and returns the number of partitions with a mismatch."""
    bad = 0
    for stream in StreamKind:
        base = registry.root / "_manifests" / stream_dir_name(stream)
        if not base.is_dir():
            continue
        symbols = sorted(d.name.split("=", 1)[1] for d in base.glob("symbol=*") if d.is_dir())
        for symbol in symbols:
            for paths in registry.manifested_partitions(stream, symbol):
                try:
                    await verify_partition(paths, events)
                except StorageExportVerifyFailed:
                    bad += 1
    storage_scrub_last_run_timestamp_seconds.set(clock().timestamp())
    return bad


async def run_weekly_scrub(
    registry: DatasetRegistry,
    events: SystemEventSink,
    *,
    interval_s: float = SCRUB_INTERVAL_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Supervisor-owned loop: scrub, then sleep `interval_s`; honours cancellation."""
    while True:
        try:
            bad = await scrub_all(registry, events, clock)
            await events.emit("INFO", "STORAGE_COLD_SCRUB_RUN", {"mismatches": bad})
        except Exception:
            logger.exception("cold_scrub_run_failed")
            await events.emit("WARNING", "STORAGE_COLD_SCRUB_FAILED", {})
        await sleep(interval_s)


class ScrubTask:
    """Tracked, cancellable owner of the weekly scrub loop (C-2.18)."""

    def __init__(
        self,
        registry: DatasetRegistry,
        events: SystemEventSink,
        *,
        interval_s: float = SCRUB_INTERVAL_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._registry = registry
        self._events = events
        self._interval_s = interval_s
        self._sleep = sleep
        self._clock = clock
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(
                run_weekly_scrub(
                    self._registry,
                    self._events,
                    interval_s=self._interval_s,
                    sleep=self._sleep,
                    clock=self._clock,
                ),
                name="cold-weekly-scrub",
            )

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
