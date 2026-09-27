"""`ColdTierRepository` — Parquet/DuckDB export, manifest, and verification.

See ADR-0003 (repository rule) and `docs/plan/21-database-schema.md` Sec.4
for the partition layout this Protocol's methods operate over. Ordering
guarantee: `query` returns rows ordered by ascending timestamp column, same
as the hot-tier read methods, so callers merging hot+cold results never need
to re-sort across the tier boundary.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from candleviewer.storage.models import ExportRun, StreamKind, TimeRange


@runtime_checkable
class ColdTierRepository(Protocol):
    """Parquet/DuckDB cold-tier export, catalogue, and query surface."""

    async def export_partition(self, symbol: str, stream: StreamKind, rng: TimeRange) -> ExportRun:
        """Export one `(symbol, stream)` partition covering `rng` from the hot
        tier to Parquet. Returns an `ExportRun` with `verified=False` —
        callers must call `verify_checksums` before treating the export as
        durable (ticket "Technical notes / design")."""
        ...

    async def list_manifest(self, symbol: str, stream: StreamKind) -> list[ExportRun]:
        """List every recorded export for `(symbol, stream)`, ascending by
        `partition_range.start_us`."""
        ...

    async def query(self, symbol: str, stream: StreamKind, rng: TimeRange) -> list[dict[str, Any]]:
        """Ad-hoc DuckDB query over the cold tier for `(symbol, stream)`
        within `rng`. Returns plain dicts (not the hot-path row dataclasses)
        because cold-tier query shape varies by stream and callers are
        expected to be low-frequency (replay, backfill, export tooling), not
        the render-critical hot path."""
        ...

    async def verify_checksums(self, run: ExportRun) -> bool:
        """Verify a previously exported partition's on-disk checksums still
        match the manifest. Raises `StorageExportVerifyFailed` on mismatch
        rather than returning `False`, so callers cannot silently ignore a
        corrupted export; returns `True` on success."""
        ...
