"""Reproducible storage-growth estimator for spike E16-K01 (S6).

Reads the recorded public-feed corpus (`CORPUS`) (no network), builds the QuestDB hot-tier rows each
stream would produce, and reports (a) wire bytes/day, (b) ILP and modelled on-disk
bytes per row, (c) real Parquet bytes per row via the E07 cold writer profile, and
(d) GB/day projections. Run from `services/api`:

    PYTHONPATH=. python bench/storage_measure.py --out-dir /tmp/s6

The corpus is a *documented-shape* capture (exception #1778 A), not live traffic:
its frame rates are NOT a substitute for a 7-day live run (see the E16-K01 note).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow as pa

from candleviewer.storage.cold.writer import MARKET_DATA_PROFILE, write_parquet_file
from candleviewer.storage.questdb.ilp_writer import TableSchema, serialize_ilp_line
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS

REPO_ROOT = Path(__file__).resolve().parents[3]
# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
CORPUS = REPO_ROOT / "packages" / "fixtures" / "bybit" / "2026-10-05" / "ws"
DDL = REPO_ROOT / "backend" / "db" / "questdb" / "0001_core_tables.sql"
DAY_S = 86_400
GB = 1e9

#: ADR / 21-database-schema.md Sec.11.1 reference rows/day (BTCUSDT-class), used for the
#: *modelled-rate* column because the corpus frame rates are synthetic.
REFERENCE_ROWS_DAY = {
    "trades": 2_500_000,
    "orderbook_deltas": 190_000_000,
    "orderbook_snapshots": 1_500,
    "tickers": 864_000,
}
#: Fixed on-disk widths (bytes) per QuestDB column type; STRING is modelled per value.
_WIDTH = {"TIMESTAMP": 8, "DOUBLE": 8, "LONG": 8, "INT": 4, "BOOLEAN": 1, "SYMBOL": 4}
_COL_RE = re.compile(r"^\s*(\w+)\s+([A-Z]+)\b")


def parse_column_types(sql: Path, table: str) -> dict[str, str]:
    """`{column: TYPE}` for one table of the hot-tier DDL (hand-rolled, tiny)."""
    text = sql.read_text(encoding="utf-8")
    body = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\)\s*TIMESTAMP", text, re.S)
    if body is None:
        raise ValueError(f"table {table} not found in {sql.name}")
    cols: dict[str, str] = {}
    for line in body.group(1).splitlines():
        match = _COL_RE.match(line.split("--")[0])
        if match:
            cols[match.group(1)] = match.group(2)
    return cols


def modelled_row_bytes(types: dict[str, str], row: dict[str, Any]) -> int:
    """On-disk bytes for one row: fixed widths, STRING = 8 B offset + 4 B len + UTF-16."""
    total = 0
    for col, typ in types.items():
        if typ == "STRING":
            total += 12 + 2 * len(str(row.get(col, "")))
        else:
            total += _WIDTH[typ]
    return total


def load_frames(name: str) -> list[dict[str, Any]]:
    path = CORPUS / name
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def window_s(frames: list[dict[str, Any]]) -> float:
    return float(max((frames[-1]["ts"] - frames[0]["ts"]) / 1000.0, 1.0))


def wire_bytes(name: str) -> int:
    return sum(len(x.encode("utf-8")) + 1 for x in (CORPUS / name).read_text("utf-8").splitlines())


# --------------------------------------------------------------------------- row builders


def trade_rows(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for seq, (frame, t) in enumerate((f, t) for f in frames for t in f["data"]):
        price, size = float(t["p"]), float(t["v"])
        rows.append(
            {
                "ts": t["T"] * 1000, "recv_ts": frame["ts"] * 1000, "symbol": t["s"],
                "side": t["S"], "price": price, "size": size, "notional": price * size,
                "trade_id": t["i"], "tick_dir": t["L"], "is_block": t["BT"], "seq": seq,
            }
        )  # fmt: skip
    return rows


def delta_rows(
    frames: list[dict[str, Any]], depth: int, max_rank: int | None
) -> list[dict[str, Any]]:
    """Explode book deltas to one row per level; `max_rank` drops levels beyond N ticks
    of the opening best bid/ask (a static-book proxy for a depth-N subscription)."""
    snap = next(f for f in frames if f["type"] == "snapshot")
    best_bid = max(float(p) for p, _ in snap["data"]["b"])
    best_ask = min(float(p) for p, _ in snap["data"]["a"])
    rows: list[dict[str, Any]] = []
    for f in frames:
        if f["type"] != "delta":
            continue
        d = f["data"]
        for side, key, ref in (("bid", "b", best_bid), ("ask", "a", best_ask)):
            for price_s, size_s in d[key]:
                if max_rank is not None and abs(float(price_s) - ref) / 0.1 > max_rank:
                    continue
                size = float(size_s)
                rows.append(
                    {
                        "ts": f["ts"] * 1000, "recv_ts": f["ts"] * 1000 + 700,
                        "symbol": d["s"], "depth": depth, "side": side,
                        "price": float(price_s), "size": size,
                        "action": "delete" if size == 0 else "update",
                        "update_id": d["u"], "cross_seq": d["seq"], "epoch_id": 1,
                    }
                )  # fmt: skip
    return rows


def snapshot_rows(frames: list[dict[str, Any]], depth: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for f in frames:
        if f["type"] != "snapshot":
            continue
        d = f["data"]
        bids, asks = d["b"][:depth], d["a"][:depth]
        rows.append(
            {
                "ts": f["ts"] * 1000, "recv_ts": f["ts"] * 1000 + 700, "symbol": d["s"],
                "depth": depth, "epoch_id": 1, "update_id": d["u"], "cross_seq": d["seq"],
                "source": "exchange", "bids": json.dumps(bids, separators=(",", ":")),
                "asks": json.dumps(asks, separators=(",", ":")),
                "level_count": len(bids) + len(asks), "checksum": 123456789,
            }
        )  # fmt: skip
    return rows


def ticker_rows(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge delta frames into running state; one full row per frame (as the ingester does)."""
    state: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for f in frames:
        state.update(f["data"])
        s = state
        rows.append(
            {
                "ts": f["ts"] * 1000, "recv_ts": f["ts"] * 1000 + 700, "symbol": s["symbol"],
                "last_price": float(s["lastPrice"]), "mark_price": float(s["markPrice"]),
                "index_price": float(s["indexPrice"]), "bid1_price": float(s["bid1Price"]),
                "bid1_size": float(s["bid1Size"]), "ask1_price": float(s["ask1Price"]),
                "ask1_size": float(s["ask1Size"]), "volume_24h": float(s["volume24h"]),
                "turnover_24h": float(s["turnover24h"]),
                "price_24h_pcnt": float(s["price24hPcnt"]), "high_24h": float(s["lastPrice"]),
                "low_24h": float(s["lastPrice"]), "open_interest": float(s["openInterest"]),
                "open_interest_value": float(s["openInterestValue"]),
                "funding_rate": float(s["fundingRate"]),
                "next_funding_ts": int(s["nextFundingTime"]) * 1000,
                "basis": float(s["markPrice"]) - float(s["indexPrice"]),
            }
        )  # fmt: skip
    return rows


# --------------------------------------------------------------------------- measurement


def measure_table(table: str, rows: list[dict[str, Any]], tmp: Path) -> dict[str, Any]:
    """ILP bytes/row, modelled on-disk bytes/row and real Parquet bytes/row for `rows`."""
    schema: TableSchema = ALL_SCHEMAS[table]
    types = parse_column_types(DDL, table)
    ilp = [
        len(serialize_ilp_line(schema, {k: v for k, v in r.items() if k != "ts"}, r["ts"]).encode())
        + 1
        for r in rows
    ]
    model = [modelled_row_bytes(types, r) for r in rows]
    arrow = pa.Table.from_pylist(rows).sort_by("ts")
    dest = tmp / f"{table}.parquet"
    write_parquet_file(arrow, dest, profile=MARKET_DATA_PROFILE, rows_per_group=1_000_000)
    pq_bytes = dest.stat().st_size
    n = len(rows)
    return {
        "rows": n,
        "ilp_bytes_per_row": round(statistics.fmean(ilp), 1),
        "hot_model_bytes_per_row": round(statistics.fmean(model), 1),
        "parquet_bytes_per_row": round(pq_bytes / n, 1),
        "hot_to_cold_ratio": round(sum(model) / pq_bytes, 2),
    }


def rate_windows(frames: list[dict[str, Any]], bucket_s: int = 600) -> dict[str, float]:
    """Wire bytes/s per bucket -> mean, peak (max bucket), quiet (min bucket), peak/quiet."""
    per: dict[int, int] = defaultdict(int)
    t0 = frames[0]["ts"]
    for f in frames:
        per[(f["ts"] - t0) // (bucket_s * 1000)] += len(json.dumps(f, separators=(",", ":")))
    rates = [v / bucket_s for v in per.values()]
    return {
        "mean_Bps": statistics.fmean(rates),
        "peak_Bps": max(rates),
        "quiet_Bps": min(rates),
        "peak_over_quiet": max(rates) / max(min(rates), 1e-9),
    }


# (symbol, table, corpus file, depth) cases; ETH has no 3 h book capture, so only trades.
_CASES: list[tuple[str, str, str, int | None]] = [
    ("BTCUSDT", "trades", "clean_publicTrade_BTCUSDT.jsonl", None),
    ("ETHUSDT", "trades", "clean_publicTrade_ETHUSDT.jsonl", None),
    ("BTCUSDT", "orderbook_deltas", "orderbook_BTCUSDT.jsonl", 200),
    ("BTCUSDT", "orderbook_deltas", "orderbook_BTCUSDT.jsonl", 50),
    ("BTCUSDT", "orderbook_snapshots", "orderbook_BTCUSDT.jsonl", 200),
    ("BTCUSDT", "orderbook_snapshots", "orderbook_BTCUSDT.jsonl", 50),
    ("BTCUSDT", "tickers", "burst_tickers_BTCUSDT.jsonl", None),
]


def build_rows(table: str, frames: list[dict[str, Any]], depth: int | None) -> list[dict[str, Any]]:
    if table == "trades":
        return trade_rows(frames)
    if table == "orderbook_deltas":
        return delta_rows(frames, depth or 200, None if depth == 200 else depth)
    if table == "orderbook_snapshots":
        return snapshot_rows(frames, depth or 200)
    return ticker_rows(frames)


def run(limit: int | None = None) -> dict[str, Any]:
    """Measure every case. `limit` truncates each corpus file (unit-test slice)."""
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as td:
        for symbol, table, fname, depth in _CASES:
            frames = load_frames(fname)
            if table == "trades":
                frames = [f for f in frames if "data" in f]
            if limit is not None:
                frames = frames[:limit]
            rows = build_rows(table, frames, depth)
            if not rows:
                continue
            tmp = Path(td) / f"{symbol}_{depth}"
            tmp.mkdir(exist_ok=True)
            m = measure_table(table, rows, tmp)
            span = window_s(frames)
            m.update(
                symbol=symbol, table=table, depth=depth, window_s=span,
                corpus_rows_per_day=round(m["rows"] / span * DAY_S),
                wire_bytes_per_day=round(wire_bytes(fname) / span * DAY_S),
                wire=rate_windows(frames),
            )  # fmt: skip
            ref = REFERENCE_ROWS_DAY.get(table)
            if ref is not None:
                scale = 0.25 if (table == "orderbook_deltas" and depth == 50) else 1.0
                m["reference_rows_per_day"] = int(ref * scale)
                m["hot_GB_day_reference_rate"] = round(
                    ref * scale * m["hot_model_bytes_per_row"] / GB, 3
                )
                m["cold_GB_day_reference_rate"] = round(
                    ref * scale * m["parquet_bytes_per_row"] / GB, 3
                )
            m["hot_GB_day_corpus_rate"] = round(
                m["corpus_rows_per_day"] * m["hot_model_bytes_per_row"] / GB, 4
            )
            results.append(m)
    return {"corpus": str(CORPUS.relative_to(REPO_ROOT)), "results": results}


def to_markdown(report: dict[str, Any]) -> str:
    head = (
        "| symbol | table | depth | rows | ILP B/row | hot B/row (model) | Parquet B/row "
        "| hot/cold | hot GB/day @ref rate | cold GB/day @ref rate | hot GB/day @corpus rate |\n"
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|\n"
    )
    lines = [
        f"| {r['symbol']} | {r['table']} | {r['depth'] or '-'} | {r['rows']} "
        f"| {r['ilp_bytes_per_row']} | {r['hot_model_bytes_per_row']} "
        f"| {r['parquet_bytes_per_row']} | {r['hot_to_cold_ratio']} "
        f"| {r.get('hot_GB_day_reference_rate', 'n/a')} "
        f"| {r.get('cold_GB_day_reference_rate', 'n/a')} | {r['hot_GB_day_corpus_rate']} |"
        for r in report["results"]
    ]
    return head + "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    report = run(args.limit)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "storage_measure.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    (args.out_dir / "storage_measure.md").write_text(to_markdown(report), encoding="utf-8")
    print(to_markdown(report))


if __name__ == "__main__":
    main()
