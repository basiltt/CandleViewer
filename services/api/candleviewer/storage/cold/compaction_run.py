"""Weekly compaction pass over the cold tier (E16-T05, 21 §5.4).

Walks every manifested partition (optionally filtered by symbol and age) and
runs the existing `Compactor` on it — never a fork. The replay idle guard is
the compactor's own (`IdleGuard`): a partition being read is deferred
(`compaction_deferred`), logged, and the pass completes the rest.
Downsample streams past the rollup horizon are left to the roll-off's
downsampler (they are rolled up, not merged).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from candleviewer.storage.cold.compactor import Compactor
from candleviewer.storage.cold.layout import DatasetRegistry, stream_dir_name
from candleviewer.storage.errors import StorageExportVerifyFailed
from candleviewer.storage.models import StreamKind

_US_PER_DAY = 86_400_000_000
COMPACTION_DEFERRED = "compaction_deferred"


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(slots=True)
class CompactionSummary:
    compacted: int = 0
    skipped: int = 0
    deferred: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def as_result(self) -> dict[str, object]:
        return {
            "compacted": self.compacted,
            "skipped": self.skipped,
            "deferred": list(self.deferred),
            "failed": list(self.failed),
        }


def _day_end_us(partition_parts: tuple[str, ...]) -> int | None:
    for part in partition_parts:
        if part.startswith("dt="):
            day = datetime.strptime(part[3:], "%Y-%m-%d").replace(tzinfo=UTC)
            return int(day.timestamp()) * 1_000_000 + _US_PER_DAY
    return None


async def compact_all(
    registry: DatasetRegistry,
    compactor: Compactor,
    *,
    symbols: list[str] | None = None,
    older_than_days: int | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    on_progress: Callable[[float], None] | None = None,
) -> CompactionSummary:
    summary = CompactionSummary()
    now_us = int(clock().timestamp() * 1_000_000)
    cutoff = None if older_than_days is None else now_us - older_than_days * _US_PER_DAY
    work = []
    for stream in StreamKind:
        base = registry.root / "_manifests" / stream_dir_name(stream)
        if not base.is_dir():
            continue
        found = sorted(d.name.split("=", 1)[1] for d in base.glob("symbol=*") if d.is_dir())
        for symbol in found:
            if symbols is not None and symbol not in symbols:
                continue
            parts = await asyncio.to_thread(registry.manifested_partitions, stream, symbol)
            for paths in parts:
                end = _day_end_us(paths.partition_dir.parts)
                if cutoff is not None and (end is None or end > cutoff):
                    continue
                work.append(paths)
    for i, paths in enumerate(work):
        rel = paths.partition_dir.relative_to(paths.root).as_posix()
        try:
            res = await compactor.compact_partition(
                paths.partition_dir, paths.root, paths.manifests_dir
            )
        except StorageExportVerifyFailed:
            summary.failed.append(rel)
            logger().warning("compaction_failed", partition=rel)
        else:
            if res.skipped and res.reason.startswith("active replay"):
                summary.deferred.append(rel)
                logger().info(COMPACTION_DEFERRED, partition=rel, code=COMPACTION_DEFERRED)
            elif res.skipped:
                summary.skipped += 1
            else:
                summary.compacted += 1
        if on_progress is not None:
            on_progress(100.0 * (i + 1) / len(work))
    return summary
