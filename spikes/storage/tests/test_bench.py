"""Harness self-test for spikes/storage/bench.py (E07-K01).

Not a CI performance gate for a production repository (E07-T03 owns that);
this only asserts the harness runs end-to-end on the synthetic dataset,
produces well-formed p50/p95/p99 + meets_target for every shape x engine
pair, and that the decision rule is deterministic and reproducible for a
fixed seed -- the harness's own "Test plan" self-test requirement.
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
    run_all,
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


def test_run_all_is_reproducible_across_runs_with_the_same_seed() -> None:
    # The *dataset* (row counts, values, ordering) is fully deterministic for
    # a fixed seed (see test_build_dataset_is_deterministic_for_a_fixed_seed);
    # wall-clock scan timings inherently carry machine-noise jitter run to
    # run, so this only asserts the decision and result-row counts are
    # stable, not that timings are bit-identical.
    r1 = run_all(seed=3)
    r2 = run_all(seed=3)
    assert r1["decision"]["decision"] == r2["decision"]["decision"]
    for shape_id in r1["shapes"]:
        rows1 = r1["shapes"][shape_id]["_by_symbol"][SYMBOLS[0]]["questdb"]["result_rows"]
        rows2 = r2["shapes"][shape_id]["_by_symbol"][SYMBOLS[0]]["questdb"]["result_rows"]
        assert rows1 == rows2
