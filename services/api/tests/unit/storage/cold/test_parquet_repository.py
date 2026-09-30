"""Unit tests: `ParquetColdTierRepository` — Protocol conformance, query
round-trip, verify-on-read quarantine (AC 3), dataset-id registry (AC 9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from candleviewer.storage.cold.layout import DatasetNotRegistered, DatasetRegistry
from candleviewer.storage.cold.parquet_repository import (
    DownsampleNotImplemented,
    ParquetColdTierRepository,
    downsample,
)
from candleviewer.storage.errors import StorageExportVerifyFailed
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.cold import ColdTierRepository
from tests.unit.storage.cold._helpers import (
    DAY_START_US,
    FakeHotSource,
    RecordingSink,
    day_range,
    trades_table,
)

PART = Path("trades") / "symbol=BTCUSDT" / "dt=2026-10-17"


def _repo(root: Path, n: int = 5, sink: RecordingSink | None = None) -> ParquetColdTierRepository:
    return ParquetColdTierRepository(
        DatasetRegistry(root), FakeHotSource(trades_table(n)), events=sink
    )


def test_repository_is_protocol_conformant(tmp_path: Path) -> None:
    assert isinstance(_repo(tmp_path), ColdTierRepository)


async def test_export_then_query_round_trips_rows_in_ts_order(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 5)
    await repo.export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    sub = TimeRange(start_us=DAY_START_US + 1, end_us=DAY_START_US + 4)
    rows = await repo.query("BTCUSDT", StreamKind.TRADES, sub)
    assert [int(r["ts"].timestamp() * 1_000_000) for r in rows] == [
        DAY_START_US + 1,
        DAY_START_US + 2,
        DAY_START_US + 3,
    ]
    assert all(r["ts"].utcoffset().total_seconds() == 0 for r in rows)
    assert await repo.query("ETHUSDT", StreamKind.TRADES, day_range()) == []


async def test_list_manifest_and_verify_checksums(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 4)
    run = await repo.export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    [listed] = await repo.list_manifest("BTCUSDT", StreamKind.TRADES)
    assert (listed.run_id, listed.row_count, listed.partition_range) == (
        run.run_id,
        4,
        day_range(),
    )
    assert await repo.verify_checksums(run) is True
    assert await repo.list_manifest("ETHUSDT", StreamKind.TRADES) == []


async def test_corrupted_byte_is_quarantined_alerted_and_never_served(tmp_path: Path) -> None:
    sink = RecordingSink()
    repo = _repo(tmp_path, 5, sink)
    await repo.export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    f = tmp_path / PART / "part-0000.parquet"
    data = bytearray(f.read_bytes())
    data[len(data) // 2] ^= 0x01
    f.write_bytes(bytes(data))
    with pytest.raises(StorageExportVerifyFailed):
        await repo.query("BTCUSDT", StreamKind.TRADES, day_range())
    assert sink.events[-1][:2] == ("CRITICAL", "STORAGE_COLD_FILE_QUARANTINED")
    assert (tmp_path / "_quarantine" / PART / "part-0000.parquet").exists()
    assert await repo.query("BTCUSDT", StreamKind.TRADES, day_range()) == []


async def test_missing_file_is_flagged(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 2, RecordingSink())
    run = await repo.export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    (tmp_path / PART / "part-0000.parquet").unlink()
    with pytest.raises(StorageExportVerifyFailed, match="missing"):
        await repo.verify_checksums(run)


@pytest.mark.parametrize("symbol", ["../../etc/passwd", "..", "/etc", "C:\\x", "a/b", ""])
async def test_query_rejects_traversal_symbols_without_reading(tmp_path: Path, symbol: str) -> None:
    with pytest.raises(DatasetNotRegistered):
        await _repo(tmp_path).query(symbol, StreamKind.TRADES, day_range())
    with pytest.raises(DatasetNotRegistered):
        await _repo(tmp_path).list_manifest(symbol, StreamKind.TRADES)


async def test_query_rejects_stream_not_addressable_by_day(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not addressable"):
        await _repo(tmp_path).query("BTCUSDT", StreamKind.KLINES, day_range())


def test_downsample_raises_not_implemented_referencing_e16() -> None:
    with pytest.raises(DownsampleNotImplemented, match="E16"):
        downsample(StreamKind.ORDERBOOK_DELTA, day_range())
