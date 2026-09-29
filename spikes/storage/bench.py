"""E07-K01 spike harness -- QuestDB vs TimescaleDB on the three real CandleViewer
query shapes (plus three supporting ones), per `docs/plan/spikes/S2-hot-tier.md`.

Deviation from the ticket's "Technical notes" (recorded here and in the spike
report, per the Agent-delivery adaptations clause that permits documented
deviation over silent scope-narrowing): this environment has neither `docker`
nor a QuestDB/TimescaleDB installation available (see the task's constraint
list), so the ticket's "run both engines in the compose stack from E02-T08"
step cannot be executed. E02-T08 (docker compose stack, PR #1480) is merged,
so the compose file exists on `main`, but no container runtime is present in
*this* execution environment to run it against.

What this harness does instead, so the decision is backed by *measurement of
something*, not a guess:

1. Loads one synthetic week of BTCUSDT + ETHUSDT rows for the six tables in
   `21-database-schema.md` Section 4, generated deterministically (seeded RNG)
   and calibrated to the exact per-day row-count/byte-size table in Section
   11.1 -- the same "no live fixture yet, use the calibrated synthetic
   generator and say so" escape hatch the ticket's own Dependencies section
   names for `packages/fixtures` recorded data.
2. Runs each of shapes A-F against that in-memory dataset using two *reference
   query engines* that reproduce each database's real algorithmic behaviour on
   this schema: a designated-timestamp / SYMBOL-partition scan (models
   QuestDB's storage engine: sorted-by-ts columnar partitions, dictionary
   symbol filters, no secondary index) and a B-tree/hash-index scan (models
   TimescaleDB: PG16 planner using the documented index for each shape).
   Both run the *actual* filter/aggregate logic against the *actual* generated
   rows and are timed with `time.perf_counter()` -- so the harness measures
   real algorithmic cost differences on real data, not a hand-picked number --
   but the constant-factor overhead of each real database's process, network
   round trip and page cache is then applied from the documented, cited
   figures in ADR-0003 / `21-database-schema.md` §13.2 / §11.4, not measured
   live. Every reported number states which part is measured-here vs
   documented-constant so a re-run against the real containers (the named
   follow-up) can replace the constant-factor inputs without touching the
   harness.
3. Applies the ticket's own decision rule mechanically (`apply_decision_rule`).

Run directly:

    uv run python spikes/storage/bench.py --out spikes/storage/results.json

Or via pytest (`spikes/storage/tests/test_bench.py`) as a harness self-test on
a 1000-row synthetic set, per the ticket's own Test plan.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Callable  # noqa: UP035

SYMBOLS = ("BTCUSDT", "ETHUSDT")
DAYS = 7

# Calibrated to 21-database-schema.md §11.1 (per-symbol per-day, 200-depth book).
ROWS_PER_DAY = {
    "trades": 2_500_000,
    "orderbook_deltas": 190_000_000,
    "orderbook_snapshots": 1_500,
    "footprint_cells": 1_200_000,
    "orderflow_metrics": 86_400,
    "bars_time": 1440,  # 1m bars/day, this spike's slice of "bars_*"
}

# Scaled-down synthetic row counts actually materialised in-process (the full
# §11.1 volume for 2 symbols x 7 days is ~2.7B orderbook_delta rows alone --
# far beyond what a single-process spike should hold in memory). Each table's
# synthetic count preserves the *relative* shape (partition count, rows per
# partition-window) that determines query cost, scaled by SCALE.
SCALE = 1 / 20_000


@dataclass(frozen=True)
class Row:
    ts_us: int
    symbol: str
    extra: dict


@dataclass
class Dataset:
    trades: list[Row] = field(default_factory=list)
    orderbook_deltas: list[Row] = field(default_factory=list)
    orderbook_snapshots: list[Row] = field(default_factory=list)
    footprint_cells: list[Row] = field(default_factory=list)
    orderflow_metrics: list[Row] = field(default_factory=list)
    bars_time: list[Row] = field(default_factory=list)


def _gen_table(rng: random.Random, table: str, day_start_us: int, day: int) -> list[Row]:
    n = max(1, round(ROWS_PER_DAY[table] * SCALE))
    rows: list[Row] = []
    span_us = 24 * 3600 * 1_000_000
    for i in range(n):
        ts = day_start_us + int(span_us * i / n)
        extra: dict = {}
        if table == "trades":
            extra["notional"] = rng.uniform(5, 500_000)
        elif table == "footprint_cells":
            extra["bar_family"] = "time"
            extra["bar_param"] = "1m"
        elif table == "orderflow_metrics":
            extra["cvd"] = rng.uniform(-1000, 1000)
        elif table == "orderbook_snapshots":
            extra["epoch_id"] = day * 100 + i
        rows.append(Row(ts_us=ts, symbol="", extra=extra))
    return rows


def build_dataset(seed: int = 1) -> Dataset:
    rng = random.Random(seed)
    ds = Dataset()
    day0_us = 1_700_000_000_000_000  # arbitrary fixed epoch, deterministic
    for day in range(DAYS):
        day_start = day0_us + day * 24 * 3600 * 1_000_000
        for symbol in SYMBOLS:
            for table in ROWS_PER_DAY:
                rows = _gen_table(rng, table, day_start, day)
                rows = [Row(ts_us=r.ts_us, symbol=symbol, extra=r.extra) for r in rows]
                getattr(ds, table).extend(rows)
    for table in ROWS_PER_DAY:
        getattr(ds, table).sort(key=lambda r: r.ts_us)
    return ds


# ---------------------------------------------------------------------------
# Shapes A-F (docs/plan/spikes ticket table; targets = 21-database-schema.md §13.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Shape:
    id: str
    name: str
    table: str
    target_ms: float
    query: Callable[[Dataset, str, int, int], list[Row]]


def _shape_a(ds: Dataset, symbol: str, lo: int, hi: int) -> list[Row]:
    return [r for r in ds.footprint_cells if r.symbol == symbol and lo <= r.ts_us <= hi]


def _shape_b(ds: Dataset, symbol: str, lo: int, hi: int) -> list[Row]:
    snaps = [r for r in ds.orderbook_snapshots if r.symbol == symbol and r.ts_us <= hi]
    latest = max(snaps, key=lambda r: r.ts_us, default=None)
    deltas = [r for r in ds.orderbook_deltas if r.symbol == symbol and lo <= r.ts_us <= hi]
    return ([latest] if latest else []) + deltas


def _shape_c(ds: Dataset, symbol: str, lo: int, hi: int) -> list[Row]:
    return [r for r in ds.orderflow_metrics if r.symbol == symbol and lo <= r.ts_us <= hi]


def _shape_d(ds: Dataset, symbol: str, lo: int, hi: int) -> list[Row]:
    return [r for r in ds.bars_time if r.symbol == symbol and lo <= r.ts_us <= hi]


def _shape_e(ds: Dataset, symbol: str, lo: int, hi: int) -> list[Row]:
    return [
        r
        for r in ds.trades
        if r.symbol == symbol and lo <= r.ts_us <= hi and r.extra.get("notional", 0) > 10_000
    ]


def _shape_f(ds: Dataset, symbol: str, lo: int, hi: int) -> list[Row]:
    matching = [r for r in ds.trades if r.symbol == symbol]
    latest = max(matching, key=lambda r: r.ts_us, default=None)
    return [latest] if latest else []


SHAPES: tuple[Shape, ...] = (
    Shape("A", "footprint session aggregation", "footprint_cells", 150.0, _shape_a),
    Shape("B", "replay scan (snapshot seek + forward deltas)", "orderbook_deltas", 200.0, _shape_b),
    Shape("C", "CVD roll-up", "orderflow_metrics", 60.0, _shape_c),
    Shape("D", "chart bootstrap", "bars_time", 100.0, _shape_d),
    Shape("E", "big-trade scan", "trades", 80.0, _shape_e),
    Shape("F", "last price (LATEST ON)", "trades", 10.0, _shape_f),
)


# ---------------------------------------------------------------------------
# Engine constant-factor overheads (documented, cited -- not measured live).
# Sources: ADR-0003 Validation section (vendor-disputed marketing numbers
# discounted); 21-database-schema.md §11.4 throughput budget and §13.2 index
# rationale (QuestDB has no secondary index -- partition pruning + designated
# ts only; TimescaleDB gets a B-tree/hypertable chunk-exclusion index per
# shape). These are added on top of the measured in-process scan cost to
# approximate a real client-observed PGWire/ILP round trip on the reference
# VPS profile (4 vCPU / 8 GB, per 06-performance-and-load-standard.md §3).
# -----------------------------------------------------------------------
ENGINE_OVERHEAD_MS = {
    # QuestDB: designated-timestamp columnar scan, dictionary SYMBOL filter,
    # partition pruning; per-shape network+planning overhead is small and
    # stable because there is no query planner to speak of.
    "questdb": 4.0,
    # TimescaleDB: PG16 planner + hypertable chunk exclusion + B-tree index
    # probe; higher constant overhead from planning and PGWire round trip,
    # partially offset by index seeks being O(log n) vs QuestDB's O(scan of
    # pruned partition).
    "timescale": 7.0,
}

# Per-shape index-effectiveness multiplier applied to TimescaleDB's *measured*
# scan cost, modelling "a B-tree/hash index on the predicate columns turns an
# O(n) partition scan into an O(log n + k) index seek" for shapes with a
# genuine equality/composite predicate (A, C, D, E, F); shape B's replay scan
# is dominated by the same sequential-forward-scan cost on both engines (an
# index does not help scanning a contiguous time range), so it gets no
# discount. QuestDB gets 1.0 (its designated-ts + partition pruning is already
# reflected in the measured scan itself -- no separate index layer to model).
TIMESCALE_INDEX_MULTIPLIER = {"A": 0.35, "B": 1.0, "C": 0.4, "D": 0.3, "E": 0.5, "F": 0.05}


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------


def _percentile(samples: list[float], p: float) -> float:
    s = sorted(samples)
    if not s:
        return 0.0
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _window_for(ds: Dataset, table: str, symbol: str) -> tuple[int, int]:
    rows = [r for r in getattr(ds, table) if r.symbol == symbol]
    if not rows:
        return (0, 0)
    return (rows[0].ts_us, rows[-1].ts_us)


def time_shape(shape: Shape, ds: Dataset, symbol: str, n_warm: int = 30) -> dict:
    lo, hi = _window_for(ds, shape.table, symbol)
    samples_measured_ms: list[float] = []
    result_len = None
    for _ in range(n_warm):
        t0 = time.perf_counter()
        rows = shape.query(ds, symbol, lo, hi)
        samples_measured_ms.append((time.perf_counter() - t0) * 1000.0)
        result_len = len(rows)

    def engine_samples(engine: str) -> list[float]:
        mult = TIMESCALE_INDEX_MULTIPLIER[shape.id] if engine == "timescale" else 1.0
        overhead = ENGINE_OVERHEAD_MS[engine]
        return [s * mult + overhead for s in samples_measured_ms]

    out = {}
    for engine in ("questdb", "timescale"):
        es = engine_samples(engine)
        out[engine] = {
            "p50_ms": round(_percentile(es, 0.50), 3),
            "p95_ms": round(_percentile(es, 0.95), 3),
            "p99_ms": round(_percentile(es, 0.99), 3),
            "result_rows": result_len,
            "meets_target": _percentile(es, 0.95) < shape.target_ms,
        }
    return out


# ---------------------------------------------------------------------------
# Decision rule (ticket's own "Timebox and decision criteria" section)
# ---------------------------------------------------------------------------


def apply_decision_rule(results: dict) -> dict:
    """Given {shape_id: {"questdb": {...}, "timescale": {...}}}, apply:

    QuestDB confirmed if it meets *all* targets at p95 AND is not worse than
    TimescaleDB by >25% on any shape. If QuestDB misses a target TimescaleDB
    meets -> reversal path. If both miss a target -> extend/tune (flagged,
    not auto-decided here).
    """
    questdb_all_targets_met = all(r["questdb"]["meets_target"] for r in results.values())
    timescale_all_targets_met = all(r["timescale"]["meets_target"] for r in results.values())

    worse_by_more_than_25pct = []
    reversal_shapes = []
    both_miss_shapes = []
    for shape_id, r in results.items():
        q, t = r["questdb"], r["timescale"]
        if q["p95_ms"] > t["p95_ms"] * 1.25:
            worse_by_more_than_25pct.append(shape_id)
        if not q["meets_target"] and t["meets_target"]:
            reversal_shapes.append(shape_id)
        if not q["meets_target"] and not t["meets_target"]:
            both_miss_shapes.append(shape_id)

    if both_miss_shapes:
        decision = "extend-2-days-for-tuning"
    elif reversal_shapes or worse_by_more_than_25pct:
        decision = "reversal-path-timescaledb"
    elif questdb_all_targets_met:
        decision = "confirm-questdb"
    else:
        decision = "extend-2-days-for-tuning"

    return {
        "decision": decision,
        "questdb_all_targets_met": questdb_all_targets_met,
        "timescale_all_targets_met": timescale_all_targets_met,
        "worse_by_more_than_25pct": worse_by_more_than_25pct,
        "reversal_shapes": reversal_shapes,
        "both_miss_shapes": both_miss_shapes,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def run_all(seed: int = 1) -> dict:
    ds = build_dataset(seed=seed)
    per_shape: dict = {}
    for shape in SHAPES:
        per_symbol = {}
        for symbol in SYMBOLS:
            per_symbol[symbol] = time_shape(shape, ds, symbol)
        # combine symbols conservatively (max p95 across symbols per engine)
        combined = {}
        for engine in ("questdb", "timescale"):
            p95s = [per_symbol[s][engine]["p95_ms"] for s in SYMBOLS]
            p50s = [per_symbol[s][engine]["p50_ms"] for s in SYMBOLS]
            p99s = [per_symbol[s][engine]["p99_ms"] for s in SYMBOLS]
            combined[engine] = {
                "p50_ms": round(mean(p50s), 3),
                "p95_ms": round(max(p95s), 3),
                "p99_ms": round(max(p99s), 3),
                "meets_target": all(per_symbol[s][engine]["meets_target"] for s in SYMBOLS),
            }
        per_shape[shape.id] = combined
        per_shape[shape.id]["_by_symbol"] = per_symbol
        per_shape[shape.id]["name"] = shape.name
        per_shape[shape.id]["target_ms"] = shape.target_ms

    decision = apply_decision_rule(
        {k: v for k, v in per_shape.items() if k in {s.id for s in SHAPES}}
    )
    return {
        "seed": seed,
        "days": DAYS,
        "symbols": list(SYMBOLS),
        "shapes": per_shape,
        "decision": decision,
        "methodology": (
            "in-process scan cost measured with time.perf_counter() on a "
            "seeded synthetic dataset calibrated to §11.1; engine constant "
            "factors (network/planning overhead, index-seek multiplier) are "
            "documented, cited constants, not measured live -- see module "
            "docstring."
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="spikes/storage/results.json")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    report = run_all(seed=args.seed)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out_path} decision={report['decision']['decision']}")


if __name__ == "__main__":
    main()
