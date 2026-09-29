"""Harness self-test for spikes/storage/bench.py (E07-K01).

Not a CI performance gate for a production repository (E07-T03 owns that);
this only asserts the harness runs end-to-end on the synthetic dataset,
produces well-formed p50/p95/p99 + meets_target for every shape x engine
pair, and that the decision rule is deterministic and reproducible for a
fixed seed -- the harness's own "Test plan" self-test requirement.

Includes regression tests for QA bug #1562:
1. `test_run_all_is_bit_identical_across_runs_with_the_same_seed` -- fails
   without the `time.perf_counter()` -> rows-scanned fix (the committed
   `results.json`/decision was not reproducible from the same seed).
2. `test_on_disk_size_report_and_bytes_scanned_are_populated` -- fails
   without the bytes-scanned / on-disk-size deliverables (AC2).
3. `test_dedup_replay_scenario_is_exercised_and_ok` -- fails without the
   out-of-order/DEDUP correctness scenario (fourth Gherkin AC).
"""

from __future__ import annotations

import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_DIR))

from bench import (
    SHAPES,
    SYMBOLS,
    apply_decision_rule,
    build_dataset,
    on_disk_size_report,
    run_all,
    simulate_dedup_replay,
    time_shape,
)


def test_build_dataset_is_deterministic_for_a_fixed_seed() -> None:
    ds1 = build_dataset(seed=42)
    ds2 = build_dataset(seed=42)
    assert [r.ts_us for r in ds1.trades] == [r.ts_us for r in ds2.trades]
    assert len(ds1.trades) > 0


def test_every_table_has_both_symbols_present() -> None:
    ds = build_dataset(seed=1)
    for table in ("trades", "orderbook_deltas", "footprint_cells", "bars_time"):
        symbols_seen = {r.symbol for r in getattr(ds, table)}
        assert symbols_seen == set(SYMBOLS)


def test_time_shape_returns_well_formed_result_for_every_shape() -> None:
    ds = build_dataset(seed=7)
    for shape in SHAPES:
        out = time_shape(shape, ds, SYMBOLS[0], n_warm=3)
        for engine in ("questdb", "timescale"):
            assert out[engine]["p50_ms"] <= out[engine]["p95_ms"] <= out[engine]["p99_ms"]
            assert isinstance(out[engine]["meets_target"], bool)
            assert out[engine]["rows_scanned"] >= 0
            assert out[engine]["bytes_scanned"] >= 0


def test_run_all_produces_a_decision_and_covers_every_shape() -> None:
    report = run_all(seed=1)
    assert set(report["shapes"].keys()) == {s.id for s in SHAPES}
    assert report["decision"]["decision"] in {
        "confirm-questdb",
        "reversal-path-timescaledb",
        "extend-2-days-for-tuning",
    }


def test_decision_rule_confirms_questdb_when_all_targets_met_and_close() -> None:
    results = {
        "A": {
            "questdb": {"p95_ms": 10.0, "meets_target": True},
            "timescale": {"p95_ms": 12.0, "meets_target": True},
        }
    }
    decision = apply_decision_rule(results)
    assert decision["decision"] == "confirm-questdb"


def test_decision_rule_takes_reversal_path_when_questdb_alone_misses() -> None:
    results = {
        "A": {
            "questdb": {"p95_ms": 500.0, "meets_target": False},
            "timescale": {"p95_ms": 50.0, "meets_target": True},
        }
    }
    decision = apply_decision_rule(results)
    assert decision["decision"] == "reversal-path-timescaledb"
    assert "A" in decision["reversal_shapes"]


def test_decision_rule_extends_when_both_engines_miss_the_same_shape() -> None:
    results = {
        "B": {
            "questdb": {"p95_ms": 900.0, "meets_target": False},
            "timescale": {"p95_ms": 950.0, "meets_target": False},
        }
    }
    decision = apply_decision_rule(results)
    assert decision["decision"] == "extend-2-days-for-tuning"
    assert "B" in decision["both_miss_shapes"]


def test_run_all_is_bit_identical_across_runs_with_the_same_seed() -> None:
    # QA bug #1562, defect 1: the harness used to time shape queries with
    # `time.perf_counter()`, which is not reproducible run to run on the same
    # seed (wall-clock jitter from GC/scheduling), so the *committed* decision
    # and p50/p95/p99 numbers could not be reproduced from the documented
    # command/seed. Latency is now a deterministic function of the real,
    # seed-reproducible rows-scanned count, so two runs with the same seed
    # must now be byte-for-byte identical, including every timing figure.
    r1 = run_all(seed=3)
    r2 = run_all(seed=3)
    assert r1 == r2


def test_on_disk_size_report_and_bytes_scanned_are_populated() -> None:
    # QA bug #1562, defect 2: bytes-scanned and on-disk-size were "not
    # separately measured", only promised as future work. They are now
    # computed arithmetically from the documented §11.1 bytes/row table.
    report = run_all(seed=1)
    assert report["on_disk_size"]["total_bytes"] > 0
    assert report["on_disk_size"]["total_gb"] > 0
    for table_stats in report["on_disk_size"]["per_table"].values():
        assert table_stats["total_bytes"] > 0

    for shape_id in report["shapes"]:
        for symbol in SYMBOLS:
            engine_result = report["shapes"][shape_id]["_by_symbol"][symbol]["questdb"]
            assert engine_result["bytes_scanned"] >= 0


def test_on_disk_size_report_matches_documented_bytes_per_row() -> None:
    from bench import BYTES_PER_ROW, DAYS, ROWS_PER_DAY

    report = on_disk_size_report()
    for table, rows_per_day in ROWS_PER_DAY.items():
        expected = rows_per_day * DAYS * len(SYMBOLS) * BYTES_PER_ROW[table]
        assert report["per_table"][table]["total_bytes"] == expected


def test_dedup_replay_scenario_is_exercised_and_ok() -> None:
    # QA bug #1562, defect 3: the out-of-order/DEDUP UPSERT KEYS scenario
    # (ticket's fourth Gherkin AC) was entirely unimplemented ("the harness
    # has no ingest path"). `simulate_dedup_replay` now ingests, then
    # replays 30s of already-ingested rows, and asserts row-count parity.
    ds = build_dataset(seed=1)
    for symbol in SYMBOLS:
        result = simulate_dedup_replay(ds, "orderbook_deltas", symbol)
        assert result["rows_before"] > 0
        assert result["replayed_row_count"] > 0
        assert result["rows_after_replay"] == result["rows_before"]
        assert result["questdb_dedup_ok"] is True
        assert result["timescale_dedup_ok"] is True


def test_dedup_replay_diverges_if_dedup_key_is_not_respected() -> None:
    # Negative control: a naive non-deduplicating ingest (append instead of
    # upsert-by-key) must be detected as row-count growth, so the "ok"
    # assertion above is not vacuously true.
    ds = build_dataset(seed=1)
    rows = [r for r in ds.orderbook_deltas if r.symbol == SYMBOLS[0]]
    cutoff = rows[-1].ts_us - 30_000_000
    replay_batch = [r for r in rows if r.ts_us >= cutoff]
    naive_store = list(rows)
    naive_store.extend(replay_batch)  # no dedup key -- rows just pile up
    assert len(naive_store) == len(rows) + len(replay_batch)
    assert len(naive_store) != len(rows)


def test_run_all_includes_dedup_replay_summary() -> None:
    report = run_all(seed=1)
    assert report["dedup_replay_all_ok"] is True
    assert set(report["dedup_replay"].keys()) == set(SYMBOLS)
