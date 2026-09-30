"""Checksum scrub (SR-094): verify on read and in the weekly scrub.

A file whose SHA-256 or row count no longer matches its manifest entry is
quarantined (moved out of the dataset tree and dropped from the manifest,
so no DuckDB view or `query()` can read it), a CRITICAL `system_events` row
is emitted and `storage_scrub_mismatches_total` is incremented. The caller
then receives `StorageExportVerifyFailed` — the Protocol's contract.
"""

from __future__ import annotations

import asyncio

import pyarrow.parquet as pq
import structlog

from candleviewer.storage.cold.layout import ColdPaths
from candleviewer.storage.cold.manifest import ManifestStore, sha256_of
from candleviewer.storage.cold.observability import (
    SystemEventSink,
    storage_scrub_mismatches_total,
)
from candleviewer.storage.errors import StorageExportVerifyFailed

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
