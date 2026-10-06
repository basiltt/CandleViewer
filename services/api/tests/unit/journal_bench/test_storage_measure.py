"""E16-K01: the storage estimator runs on a tiny corpus slice and is self-consistent."""

from __future__ import annotations

from bench import storage_measure as sm


def test_run_small_slice_reports_every_case_with_positive_sizes() -> None:
    report = sm.run(limit=40)
    tables = {(r["symbol"], r["table"], r["depth"]) for r in report["results"]}
    assert ("BTCUSDT", "trades", None) in tables
    assert ("BTCUSDT", "orderbook_deltas", 50) in tables
    for r in report["results"]:
        assert r["ilp_bytes_per_row"] > 0
        assert r["hot_model_bytes_per_row"] > 0
        assert r["parquet_bytes_per_row"] > 0


def test_depth_50_emits_no_more_delta_rows_than_depth_200() -> None:
    frames = sm.load_frames("orderbook_BTCUSDT.jsonl")[:200]
    assert len(sm.delta_rows(frames, 50, 50)) <= len(sm.delta_rows(frames, 200, None))


def test_modelled_row_bytes_uses_fixed_widths() -> None:
    types = sm.parse_column_types(sm.DDL, "orderbook_deltas")
    # 2xTS 16 + SYMBOLx3 12 + INT 4 + DOUBLEx2 16 + LONGx3 24
    assert sm.modelled_row_bytes(types, {}) == 72


def test_markdown_table_has_one_line_per_result() -> None:
    report = sm.run(limit=20)
    assert sm.to_markdown(report).count("\n") == len(report["results"]) + 2
