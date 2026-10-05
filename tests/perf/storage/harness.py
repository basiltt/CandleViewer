"""Storage performance harness (E07-Q03). One command: `python tests/perf/storage/harness.py`.

Measures what this environment can measure honestly and labels every row with its
conditions. Query shapes run on an in-process DuckDB *proxy* over a seeded synthetic
dataset (QuestDB needs docker, unavailable here); ILP ingest runs the real
`IlpWriter` against a counting transport. Re-run against the compose stack on the
reference profile (4 vCPU / 8 GB) for authoritative numbers. Refuses to run unless
CV_ENV=test. Warm and cold series are never averaged.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import duckdb
from candleviewer.storage.sql_identifiers import checked_identifier

sys.path.insert(0, str(Path(__file__).parent))
from shapes import SHAPES
from stats import summarize

WARMUP = 5
SAMPLES = 30
T0 = 1_700_000_000_000_000
SPAN = 3_600_000_000


def require_test_env() -> None:
    if os.environ.get("CV_ENV") != "test":
        raise SystemExit("storage perf harness refuses to run unless CV_ENV=test")


def conditions(dataset_id: str, engine: str, cache: str) -> dict[str, str]:
    try:
        sha = (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            or "unknown"
        )
    except OSError:
        sha = "unknown"
    return {
        "engine": engine,
        "cache": cache,
        "cpu_limit": os.environ.get("CV_CPU_LIMIT", "unrestricted"),
        "mem_limit": os.environ.get("CV_MEM_LIMIT", "unrestricted"),
        "dataset_id": dataset_id,
        "commit_sha": sha,
    }


def build_dataset(con: duckdb.DuckDBPyConnection, seed: int, n: int) -> str:
    """Seeded (setseed) set-based generation; executemany is orders slower."""
    con.execute("SELECT setseed(?)", [(seed % 1000) / 1000.0])
    t0, span = T0, SPAN

    def ts(of: str) -> str:
        return f"({t0} + i * {span} // {of})::BIGINT"

    q = [
        (
            "trades",
            (
                f"SELECT {ts(str(n))} ts,'BTCUSDT' symbol,60000+random() price,"
                f"random()*20 qty,(60000+random())*random()*20 notional FROM range({n}) t(i)"
            ),
        ),
        (
            "tickers",
            (
                f"SELECT {ts(str(max(n // 10, 1)))} ts,'BTCUSDT' symbol,60000+random() last_px "
                f"FROM range({max(n // 10, 1)}) t(i)"
            ),
        ),
        (
            "bars_time",
            (
                f"SELECT {ts(str(max(n // 5, 1)))} ts,'BTCUSDT' symbol,'1m' bar_param,"
                f"1.0 o,2.0 c FROM range({max(n // 5, 1)}) t(i)"
            ),
        ),
        (
            "footprint_cells",
            (
                f"SELECT {ts(str(n))} ts,'BTCUSDT' symbol,(i%100)::DOUBLE px,"
                f"random() vol FROM range({n}) t(i)"
            ),
        ),
        (
            "heatmap_cells",
            (
                f"SELECT {ts(str(n))} ts,'BTCUSDT' symbol,(i%200)::DOUBLE px,"
                f"random() size FROM range({n}) t(i)"
            ),
        ),
        (
            "orderbook_deltas",
            (
                f"SELECT {ts(str(2 * n))} ts,'BTCUSDT' symbol,(i%200)::DOUBLE px,"
                f"random() size FROM range({2 * n}) t(i)"
            ),
        ),
        (
            "orderflow_metrics",
            (
                f"SELECT {ts(str(n))} ts,'BTCUSDT' symbol,random()-0.5 cvd_delta "
                f"FROM range({n}) t(i)"
            ),
        ),
        (
            "profiles",
            (
                "SELECT 'BTCUSDT' symbol,'volume' profile_kind,'d1' period_ref,"
                "i::DOUBLE px,random() vol FROM range(500) t(i)"
            ),
        ),
        (
            "open_interest",
            (
                f"SELECT {ts(str(max(n // 50, 1)))} ts,'BTCUSDT' symbol,random() oi "
                f"FROM range({max(n // 50, 1)}) t(i)"
            ),
        ),
    ]
    for name, sql in q:
        stmt = "CREATE TABLE " + checked_identifier(name) + " AS " + sql  # sql: static SHAPES text
        con.execute(stmt)
    return f"synthetic-seed{seed}-n{n}"


def bounds() -> dict[str, int]:
    hi = T0 + SPAN
    return {"lo": T0, "hi": hi, "mid": (T0 + hi) // 2, "recent": hi - 60_000_000}


_COLD_CHILD = (
    "import sys,time,duckdb;"
    "c=duckdb.connect(sys.argv[1],read_only=True);"
    "t=time.perf_counter();c.execute(sys.argv[2]).fetchall();"
    "print((time.perf_counter()-t)*1000)"
)


def _cold_sample(db: Path, sql: str) -> float:
    """Fresh interpreter + fresh DuckDB instance per sample: no buffer-pool or JIT state
    survives. The OS page cache cannot be dropped without root; CI nightly restarts
    the container for the authoritative cold series."""
    r = subprocess.run(
        [sys.executable, "-c", _COLD_CHILD, str(db), sql],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(r.stdout.strip())


def run_query_shapes(
    seed: int,
    n: int,
    samples: int = SAMPLES,
    cold_samples: int = SAMPLES,
    slowdown_ms: float = 0.0,
) -> dict[str, object]:
    """Warm: one connection, WARMUP discarded iterations. Cold: fresh subprocess +
    fresh read-only DuckDB instance per sample (OS page cache not droppable without root)."""
    out: dict[str, object] = {}
    b = bounds()
    con = duckdb.connect()
    dataset_id = build_dataset(con, seed, n)
    tmp = Path(tempfile.mkdtemp(prefix="cvperf-"))
    db = tmp / "cold.duckdb"
    src = duckdb.connect(str(db))
    build_dataset(src, seed, n)
    src.close()
    for sh in SHAPES:
        sql = sh.sql.format(**b)
        for _ in range(WARMUP):
            con.execute(sql).fetchall()
        warm: list[float] = []
        for _ in range(samples):
            t = time.perf_counter()
            con.execute(sql).fetchall()
            if slowdown_ms:  # test hook: deliberate slowdown to prove the gate fires
                time.sleep(slowdown_ms / 1000)
            warm.append((time.perf_counter() - t) * 1000)
        cold = [_cold_sample(db, sql) for _ in range(cold_samples)]
        for cache, vals in (("warm", warm), ("cold", cold)):
            out[f"{sh.id}:{cache}"] = {
                "shape": sh.id,
                "name": sh.name,
                "k01_id": sh.k01_id,
                "target_ms": sh.target_ms,
                "unit": "ms",
                **summarize(vals),
                "conditions": conditions(dataset_id, "duckdb-proxy", cache),
            }
    con.close()
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    import asyncio
    import json

    from measure import measure_loop_lag, measure_storage_growth, run_cold, run_ingest
    from stats import compare_to_baseline, format_regression_report

    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--cold-samples", type=int, default=SAMPLES)
    ap.add_argument("--rows", type=int, default=20_000)
    ap.add_argument("--ingest-seconds", type=float, default=3.0)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "results.json")
    ap.add_argument("--baseline", type=Path, default=Path(__file__).parent / "baseline.json")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument(
        "--compare-only",
        type=Path,
        help="skip measuring; compare this results.json against --baseline (exit 1 on regression)",
    )
    a = ap.parse_args(argv)
    require_test_env()
    if a.compare_only is not None:
        recorded = json.loads(a.compare_only.read_text("utf-8"))["shapes"]
        cur = {
            k.split(":")[0]: float(v["p95"])
            for k, v in recorded.items()
            if k.endswith(":warm") and "p95" in v
        }
        regs = compare_to_baseline(json.loads(a.baseline.read_text("utf-8"))["p95_ms"], cur)
        if regs:
            print(format_regression_report(regs))
            return 1
        return 0
    shapes = run_query_shapes(a.seed, a.rows, cold_samples=a.cold_samples)
    ingest = asyncio.run(run_ingest(seconds=a.ingest_seconds, batch=5000))
    stress = asyncio.run(
        run_ingest(
            seconds=a.ingest_seconds,
            # batch < flush threshold and a tiny queue: the buffer fills past capacity so the
            # lone producer must self-flush (backpressure) instead of every write flushing at once
            batch=500,
            drain_delay_s=0.02,
            max_queue_rows=2_000,
            require_backpressure=True,
        )
    )
    cold = run_cold(a.seed)
    lag = asyncio.run(measure_loop_lag())
    res = {
        "shapes": shapes,
        "ingest_sustained": ingest,
        "ingest_stress": stress,
        "cold": cold,
        "reaper_loop_lag": lag,
        "storage_growth": measure_storage_growth(seed=a.seed),
    }
    a.out.write_text(json.dumps(res, indent=2), encoding="utf-8")
    current = {
        k.split(":")[0]: float(v["p95"])
        for k, v in shapes.items()
        if k.endswith(":warm") and "p95" in v
    }
    if a.update_baseline:
        a.baseline.write_text(json.dumps({"p95_ms": current}, indent=2), encoding="utf-8")
        return 0
    if a.baseline.exists():
        regs = compare_to_baseline(json.loads(a.baseline.read_text("utf-8"))["p95_ms"], current)
        if regs:
            print(format_regression_report(regs))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
