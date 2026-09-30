"""Unit tests: Parquet writer profile (sort assertion, provenance columns,
atomic write) — `21-database-schema.md` Sec.5.2."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from candleviewer.storage.cold.writer import (
    PROVENANCE_COLUMNS,
    UnsortedRowGroup,
    add_provenance_columns,
    assert_sorted_by_ts,
    write_parquet_file,
)


def _sample_table(ts_values: list[int]) -> pa.Table:
    return pa.table({"ts": pa.array(ts_values, type=pa.int64()), "price": [1.0] * len(ts_values)})


def test_assert_sorted_by_ts_accepts_monotonic() -> None:
    assert_sorted_by_ts(_sample_table([1, 2, 2, 3]))


def test_assert_sorted_by_ts_rejects_out_of_order() -> None:
    with pytest.raises(UnsortedRowGroup):
        assert_sorted_by_ts(_sample_table([1, 3, 2]))


def test_add_provenance_columns_appends_all_three() -> None:
    table = _sample_table([1, 2, 3])
    out = add_provenance_columns(
        table, export_run_id="run-1", exported_at_us=1_700_000_000_000_000, source="questdb"
    )
    for col in PROVENANCE_COLUMNS:
        assert col in out.column_names
    assert out.column("_export_run_id").to_pylist() == ["run-1", "run-1", "run-1"]
    assert out.column("_source").to_pylist() == ["questdb"] * 3


def test_write_parquet_file_round_trips_and_is_atomic(tmp_path: Path) -> None:
    table = _sample_table([1, 2, 3])
    dest = tmp_path / "trades" / "symbol=BTCUSDT" / "dt=2026-10-17" / "part-0000.parquet"
    write_parquet_file(table, dest)

    assert dest.exists()
    assert not dest.with_suffix(".parquet.tmp").exists()
    read_back = pq.read_table(dest)
    assert read_back.num_rows == 3
    assert read_back.column("ts").to_pylist() == [1, 2, 3]


def test_write_parquet_file_uses_zstd_level_6(tmp_path: Path) -> None:
    table = _sample_table([1, 2, 3])
    dest = tmp_path / "out.parquet"
    write_parquet_file(table, dest)

    meta = pq.ParquetFile(dest).metadata
    col_meta = meta.row_group(0).column(0)
    assert col_meta.compression.upper() == "ZSTD"


def test_write_parquet_file_rejects_unsorted_batch(tmp_path: Path) -> None:
    table = _sample_table([3, 1, 2])
    dest = tmp_path / "out.parquet"
    with pytest.raises(UnsortedRowGroup):
        write_parquet_file(table, dest, rows_per_group=10)
    assert not dest.exists()


def test_normalise_ts_int_micros_becomes_utc_timestamp_without_precision_loss() -> None:
    from candleviewer.storage.cold.writer import normalise_ts

    us = 1_760_659_200_123_457
    out = normalise_ts(pa.table({"ts": pa.array([us], type=pa.int64())}))
    assert out.schema.field("ts").type == pa.timestamp("us", tz="UTC")
    assert out.column("ts").cast(pa.int64()).to_pylist() == [us]


def test_normalise_ts_passthrough_and_missing_column() -> None:
    from candleviewer.storage.cold.writer import normalise_ts

    typed = pa.table({"ts": pa.array([1], type=pa.timestamp("us", tz="UTC"))})
    assert normalise_ts(typed) is typed
    no_ts = pa.table({"x": [1]})
    assert normalise_ts(no_ts) is no_ts
    ms = pa.table({"ts": pa.array([1], type=pa.timestamp("ms", tz="UTC"))})
    assert normalise_ts(ms).column("ts").cast(pa.int64()).to_pylist() == [1000]


def test_written_file_is_parquet_v2_zstd_utc_micros_with_dictionary(tmp_path: Path) -> None:
    from candleviewer.storage.cold.writer import normalise_ts

    table = normalise_ts(
        pa.table(
            {
                "ts": pa.array([1, 2], type=pa.int64()),
                "symbol": ["BTCUSDT", "BTCUSDT"],
                "price": [1.0, 2.0],
            }
        )
    )
    dest = tmp_path / "part-0000.parquet"
    write_parquet_file(table, dest)
    meta = pq.ParquetFile(dest).metadata
    assert meta.format_version == "2.6"
    col = meta.row_group(0).column(1)
    assert col.compression == "ZSTD"
    assert "RLE_DICTIONARY" in col.encodings
    ts_type = pq.ParquetFile(dest).schema_arrow.field("ts").type
    assert ts_type == pa.timestamp("us", tz="UTC")


def test_writer_rejects_regression_across_batches(tmp_path: Path) -> None:
    from candleviewer.storage.cold.writer import write_parquet_batches

    a = pa.table({"ts": pa.array([5, 6], type=pa.int64())})
    b = pa.table({"ts": pa.array([4], type=pa.int64())})
    dest = tmp_path / "p.parquet"
    with pytest.raises(UnsortedRowGroup):
        write_parquet_batches([a, b], a.schema, dest)
    assert not dest.exists()
    assert list(tmp_path.iterdir()) == []


def test_writer_row_groups_follow_rows_per_group(tmp_path: Path) -> None:
    from candleviewer.storage.cold.writer import write_parquet_batches

    t = pa.table({"ts": pa.array(range(10), type=pa.int64())})
    dest = tmp_path / "p.parquet"
    assert write_parquet_batches(t.to_batches(max_chunksize=3), t.schema, dest, rows_per_group=4)
    assert pq.ParquetFile(dest).metadata.num_rows == 10


def test_writer_rejects_nonpositive_rows_per_group(tmp_path: Path) -> None:
    from candleviewer.storage.cold.writer import AtomicParquetWriter

    with pytest.raises(ValueError, match="rows_per_group"):
        AtomicParquetWriter(
            tmp_path / "p.parquet", pa.schema([("ts", pa.int64())]), rows_per_group=0
        )


def test_writer_use_after_commit_raises(tmp_path: Path) -> None:
    from candleviewer.storage.cold.writer import AtomicParquetWriter

    schema = pa.schema([("ts", pa.int64())])
    w = AtomicParquetWriter(tmp_path / "p.parquet", schema)
    w.write(pa.table({"ts": pa.array([1], type=pa.int64())}).to_batches()[0])
    assert w.commit() == 1
    with pytest.raises(RuntimeError):
        w.write(pa.table({"ts": pa.array([2], type=pa.int64())}))
    with pytest.raises(RuntimeError):
        w.commit()
    w.abort()  # idempotent after commit: only removes a (missing) temp


def test_sweep_stale_temps_removes_only_tmp(tmp_path: Path) -> None:
    from candleviewer.storage.cold.writer import sweep_stale_temps

    (tmp_path / "part-0000.parquet.tmp").write_bytes(b"x")
    (tmp_path / "part-0000.parquet").write_bytes(b"y")
    assert sweep_stale_temps(tmp_path) == ["part-0000.parquet.tmp"]
    assert sweep_stale_temps(tmp_path / "absent") == []
    assert (tmp_path / "part-0000.parquet").exists()
