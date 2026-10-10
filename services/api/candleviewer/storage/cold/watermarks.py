"""Per-`(symbol, stream)` roll-off watermarks (E16-T05).

Persisted beside the cold-tier manifests (`<cold_root>/_manifests/_watermarks/
<stream>/symbol=<SYM>.json`) rather than in Postgres: the manifest tree is
already the source of truth for "what is in cold", so the watermark that
attributes tiers (`CoverageService`, E16-T04) lives with it and is written with
the same tmp + fsync + rename discipline. Stdlib only (no storage driver), so
the recorder module may depend on the `WatermarkStore` Protocol freely.

Invariant: `archived_through_us` never moves backwards (`advance` is a max);
`downsampled_through_us` labels the cold range replaced by 1 s snapshots.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from candleviewer.storage.cold.layout import DatasetNotRegistered, DatasetRegistry, stream_dir_name
from candleviewer.storage.models import StreamKind


@dataclass(frozen=True, slots=True)
class RollOffWatermark:
    """Hot data with `ts < archived_through_us` was verified in cold and dropped."""

    symbol: str
    stream: StreamKind
    archived_through_us: int = 0
    downsampled_through_us: int = 0
    updated_at_us: int = 0


@dataclass(frozen=True, slots=True)
class ArchiveOutcome:
    """Result of archiving one `(symbol, stream, day)` hot partition to cold.

    `verified` is True only when the written Parquet was re-read and its row
    count AND content checksum equal the hot source's, and every manifest
    SHA-256 re-verified. `reason` is an error code when not verified
    (`archive_verification_failed` | `archive_write_failed`).
    """

    symbol: str
    stream: StreamKind
    range_start_us: int
    range_end_us: int
    verified: bool
    rows: int = 0
    bytes: int = 0
    reason: str = ""


class FileWatermarkStore:
    """Atomic JSON watermark documents under the cold root (SR-097 paths)."""

    def __init__(self, registry: DatasetRegistry) -> None:
        self._registry = registry

    def _path(self, symbol: str, stream: StreamKind) -> Path:
        # Validates `symbol` with the registry's closed charset (no traversal).
        paths = self._registry.resolve_partition(
            StreamKind.TRADES, partition_values={"symbol": symbol, "dt": "x"}
        )
        base = paths.manifests_dir / "_watermarks" / stream_dir_name(stream)
        target = base / f"symbol={symbol}.json"
        if target.resolve(strict=False).parent != base.resolve(strict=False):
            raise DatasetNotRegistered("watermark path escapes the cold root")
        return target

    def _read_sync(self, symbol: str, stream: StreamKind) -> RollOffWatermark:
        path = self._path(symbol, stream)
        if not path.is_file():
            return RollOffWatermark(symbol, stream)
        raw = json.loads(path.read_text(encoding="utf-8"))
        return RollOffWatermark(
            symbol=symbol,
            stream=stream,
            archived_through_us=int(raw.get("archived_through_us", 0)),
            downsampled_through_us=int(raw.get("downsampled_through_us", 0)),
            updated_at_us=int(raw.get("updated_at_us", 0)),
        )

    def _write_sync(self, mark: RollOffWatermark) -> None:
        path = self._path(mark.symbol, mark.stream)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = asdict(mark) | {"stream": mark.stream.value}
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    async def get(self, symbol: str, stream: StreamKind) -> RollOffWatermark:
        return await asyncio.to_thread(self._read_sync, symbol, stream)

    async def advance(
        self, symbol: str, stream: StreamKind, through_us: int, *, now_us: int
    ) -> RollOffWatermark:
        """Monotone: the stored value becomes `max(current, through_us)`."""
        current = await self.get(symbol, stream)
        if through_us <= current.archived_through_us:
            return current
        mark = replace(current, archived_through_us=through_us, updated_at_us=now_us)
        await asyncio.to_thread(self._write_sync, mark)
        return mark

    async def mark_downsampled(
        self, symbol: str, stream: StreamKind, through_us: int, *, now_us: int
    ) -> RollOffWatermark:
        current = await self.get(symbol, stream)
        if through_us <= current.downsampled_through_us:
            return current
        mark = replace(current, downsampled_through_us=through_us, updated_at_us=now_us)
        await asyncio.to_thread(self._write_sync, mark)
        return mark
