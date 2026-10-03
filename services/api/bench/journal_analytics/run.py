# ruff: noqa: S608, B023  # bench-only SQL; closures run immediately inside the loop iteration
"""E41-K01 benchmark runner: Postgres vs DuckDB/Parquet vs hybrid.

    python -m bench.journal_analytics.run --dsn postgresql://... --sizes 1000 10000 100000

Needs a *scratch* Postgres (it drops/creates ``journal_trades``/``journal_trade_tags``) plus
``duckdb``/``pyarrow``.  Synthetic, seeded data only.  Writes a JSON report.
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import duckdb
import psycopg
import pyarrow as pa
import pyarrow.parquet as pq

from . import generate as g
from . import queries as q

HOT_DAYS = 90
DDL = """
DROP TABLE IF EXISTS journal_trade_tags, journal_trades CASCADE;
CREATE TABLE journal_trades (
  id uuid PRIMARY KEY, exchange_account_id uuid, symbol text NOT NULL, side text NOT NULL,
  opened_at timestamptz NOT NULL, closed_at timestamptz, hold_seconds integer,
  realised_pnl numeric(38,18) NOT NULL DEFAULT 0, fees_paid numeric(38,18) NOT NULL DEFAULT 0,
  funding_paid numeric(38,18) NOT NULL DEFAULT 0,
  net_pnl numeric(38,18) GENERATED ALWAYS AS (realised_pnl - fees_paid - funding_paid) STORED,
  r_multiple numeric(18,6), mae_r numeric(18,6), mfe_r numeric(18,6), outcome text,
  setup_name text);
CREATE TABLE journal_trade_tags (
  journal_trade_id uuid NOT NULL REFERENCES journal_trades(id) ON DELETE CASCADE,
  journal_tag_id uuid NOT NULL, PRIMARY KEY (journal_trade_id, journal_tag_id));
CREATE INDEX ix_jtt_tag ON journal_trade_tags (journal_tag_id);
CREATE INDEX ix_jt_time ON journal_trades (opened_at DESC);
CREATE INDEX ix_jt_symbol ON journal_trades (symbol, opened_at DESC);
CREATE INDEX ix_jt_account ON journal_trades (exchange_account_id, opened_at DESC);
CREATE INDEX ix_jt_outcome ON journal_trades (outcome, opened_at DESC);
CREATE INDEX ix_jt_setup ON journal_trades (lower(setup_name)) WHERE setup_name IS NOT NULL;
"""
COVERING = (
    "CREATE INDEX ix_jt_cover ON journal_trades (exchange_account_id, opened_at, symbol) "
    "INCLUDE (side, net_pnl, r_multiple, mae_r, mfe_r, setup_name, closed_at)"
)
ROLLUP = (
    "CREATE MATERIALIZED VIEW jt_daily AS SELECT date_trunc('day', opened_at) AS d, "
    "exchange_account_id, symbol, side, coalesce(setup_name,'-') AS setup, count(*) AS n, "
    "sum(net_pnl) AS net, sum(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) AS wins "
    "FROM journal_trades GROUP BY 1,2,3,4,5"
)
ROLLUP_SQL = [
    "SELECT sum(n), sum(net), sum(wins) FROM jt_daily",
    "SELECT symbol, sum(n), sum(net), sum(wins) FROM jt_daily GROUP BY 1",
    "SELECT side, sum(n), sum(net), sum(wins) FROM jt_daily GROUP BY 1",
    "SELECT setup, sum(n), sum(net), sum(wins) FROM jt_daily GROUP BY 1",
]


def pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, round(p / 100 * (len(s) - 1)))]


def timeit(fn: Callable[[], Any], reps: int) -> dict[str, float]:
    fn()  # warm-up, not counted
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": round(statistics.median(ts), 2), "p95_ms": round(pct(ts, 95), 2)}


def load_pg(cur: psycopg.Cursor[Any], ds: g.Dataset) -> None:
    cur.execute(DDL)
    cols = [c for c in g.TRADE_COLUMNS if c != "is_aggregate"]
    with cur.copy(f"COPY journal_trades ({', '.join(cols)}) FROM STDIN") as cp:
        for row in ds.trades:
            cp.write_row(row[:-1])
    with cur.copy("COPY journal_trade_tags FROM STDIN") as cp:
        for r in ds.trade_tags:
            cp.write_row(r)
    cur.execute("ANALYZE")


def write_parquet(ds: g.Dataset, d: Path) -> None:
    cols = dict(zip(g.TRADE_COLUMNS, zip(*ds.trades, strict=True), strict=True))
    dec = pa.decimal128(38, 18)
    arrays: dict[str, pa.Array] = {}
    for n, c in cols.items():
        if n in ("realised_pnl", "fees_paid", "funding_paid"):
            arrays[n] = pa.array(list(c), dec)
        elif n in ("r_multiple", "mae_r", "mfe_r"):
            arrays[n] = pa.array(list(c), pa.decimal128(18, 6))
        elif n in ("id", "exchange_account_id"):
            arrays[n] = pa.array([str(x) for x in c])
        elif n != "is_aggregate":
            arrays[n] = pa.array(list(c))
    arrays["net_pnl"] = pa.array(
        [
            a - b - c
            for a, b, c in zip(
                cols["realised_pnl"], cols["fees_paid"], cols["funding_paid"], strict=True
            )
        ],
        dec,
    )
    pq.write_table(pa.table(arrays), d / "journal_trades.parquet")
    pq.write_table(
        pa.table(
            {
                "journal_trade_id": [str(a) for a, _ in ds.trade_tags],
                "journal_tag_id": [str(b) for _, b in ds.trade_tags],
            }
        ),
        d / "journal_trade_tags.parquet",
    )


def duck(d: Path, where: str = "true") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(
        "CREATE VIEW journal_trades AS SELECT * FROM "
        f"read_parquet('{(d / 'journal_trades.parquet').as_posix()}') WHERE {where}"
    )
    con.execute(
        "CREATE VIEW journal_trade_tags AS SELECT * FROM "
        f"read_parquet('{(d / 'journal_trade_tags.parquet').as_posix()}')"
    )
    return con


def merge(parts: list[list[tuple[Any, ...]]]) -> dict[Any, list[Any]]:
    """Boundary merge of partial (k, n, net, wins, avg_r) rows: n/net/wins are additive."""
    out: dict[Any, list[Any]] = {}
    for rows in parts:
        for k, n, net, wins, _ in rows:
            a = out.setdefault(k, [0, 0, 0])
            a[0] += n
            a[1] += net or 0
            a[2] += wins
    return out


def run(dsn: str, sizes: list[int], reps: int, out: Path) -> dict[str, Any]:
    results: dict[str, Any] = {"hot_days": HOT_DAYS, "reps": reps, "rows": []}

    def rec(n: int, tier: str, name: str, r: dict[str, float]) -> None:
        results["rows"].append({"rows_n": n, "tier": tier, "query": name, **r})
        print(n, tier, name, r, flush=True)

    with psycopg.connect(dsn, autocommit=True) as pg, pg.cursor() as cur:
        for n in sizes:
            ds = g.generate(n)
            granted = [str(a) for a in g.account_ids()]
            cutoff = (g.END - timedelta(days=HOT_DAYS)).isoformat()
            load_pg(cur, ds)
            tmp = Path(tempfile.mkdtemp(prefix="cvjb"))
            write_parquet(ds, tmp)
            con, cold = duck(tmp), duck(tmp, f"opened_at < '{cutoff}'")
            tag, sym, acct = str(g.tag_ids()[0]), g.SYMBOLS[0], granted[0]
            src = q.scoped_from(granted)
            hot_src = src.replace("WHERE ", f"WHERE opened_at >= '{cutoff}' AND ", 1)
            qs: dict[str, Callable[[str], list[str]]] = {
                "a_totals": lambda s: [q.totals(s)],
                "b_all_breakdowns": q.all_breakdowns,
                "c_equity_trade": lambda s: [q.equity_trade(s)],
                "d_mae_mfe": lambda s: [q.mae_mfe(s)],
                "e_filtered": lambda s: [q.filtered(s, acct, sym, tag, "2025-01-01", "2026-01-01")],
            }
            for name, fn in qs.items():
                rec(
                    n,
                    "postgres",
                    name,
                    timeit(lambda: [cur.execute(s).fetchall() for s in fn(src)], reps),
                )
                rec(
                    n,
                    "duckdb",
                    name,
                    timeit(lambda: [con.execute(s).fetchall() for s in fn(src)], reps),
                )

                def hybrid(fn: Callable[[str], list[str]] = fn) -> Any:
                    hot = [cur.execute(s).fetchall() for s in fn(hot_src)]
                    cd = [cold.execute(s).fetchall() for s in fn(src)]
                    return list(zip(hot, cd, strict=True))

                rec(n, "hybrid", name, timeit(hybrid, reps))
            cur.execute(COVERING)
            cur.execute("ANALYZE")
            for name in ("a_totals", "b_all_breakdowns", "e_filtered"):
                fn = qs[name]
                rec(
                    n,
                    "pg+covering",
                    name,
                    timeit(lambda: [cur.execute(s).fetchall() for s in fn(src)], reps),
                )
            cur.execute(ROLLUP)
            rec(
                n,
                "pg+rollup",
                "b_partial(symbol/side/setup only; no tag/hour/dow)",
                timeit(lambda: [cur.execute(s).fetchall() for s in ROLLUP_SQL], reps),
            )
        cur.execute("DROP TABLE IF EXISTS journal_trade_tags, journal_trades CASCADE")
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 100000])
    ap.add_argument("--reps", type=int, default=7)
    ap.add_argument("--out", type=Path, default=Path("build/reports/journal-analytics-bench.json"))
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    run(a.dsn, a.sizes, a.reps, a.out)


if __name__ == "__main__":
    main()
