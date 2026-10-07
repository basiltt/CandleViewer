"""Seeded 1M-trade symbol-day derived from the recorded corpus (no network, deterministic).

The recorded public-feed corpus (`CORPUS`) is a few hundred
documented-shape prints (see its README), so it cannot itself be a 1M-row day. We bootstrap
its empirical marginals (qty, aggressor side, price step in ticks) with a seeded numpy RNG into a
random-walk day. This is SYNTHETIC-FROM-CORPUS, not a live capture; the ADR says so.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[4]
# nosemgrep: cv-adapter-isolation,cv-bybit-vocabulary-leak reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31  # noqa: E501
CORPUS = REPO_ROOT / "packages" / "fixtures" / "bybit" / "2026-10-05" / "ws"
FILES = (
    "clean_publicTrade_BTCUSDT.jsonl",
    "publicTrade_BTCUSDT.jsonl",
    "reconnect_publicTrade_ETHUSDT.jsonl",
)
TICK = 0.1  # BTCUSDT tick size; qty step 0.001 -> "lots"
LOT = 0.001
DAY_US = 86_400_000_000
T0_US = 1_700_000_000_000_000
SEED = 12001


def load_corpus() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(qty_lots, is_buy, price_step_ticks) marginals from the recorded frames."""
    qty: list[int] = []
    buy: list[bool] = []
    px: list[int] = []
    for name in FILES:
        for line in (CORPUS / name).read_text(encoding="utf-8").splitlines():
            for t in json.loads(line)["data"]:
                if t["s"] != "BTCUSDT":
                    continue
                qty.append(round(float(t["v"]) / LOT))
                buy.append(t["S"] == "Buy")
                px.append(round(float(t["p"]) / TICK))
    steps = np.diff(np.asarray(px, dtype=np.int64))
    return np.asarray(qty, dtype=np.int64), np.asarray(buy, dtype=bool), steps


def synth_day(n: int, seed: int = SEED) -> dict[str, np.ndarray]:
    """`n` trades over one UTC day as int64 columns: ts_us, price_ticks, qty_lots, is_buy."""
    qty_c, buy_c, step_c = load_corpus()
    rng = np.random.default_rng(seed)
    qty = np.maximum(1, rng.choice(qty_c, n))
    is_buy = rng.choice(buy_c, n)
    steps = rng.choice(step_c, n)
    # Zero-mean the empirical steps and add weak mean reversion so the day stays in a band.
    steps = steps - round(float(steps.mean()))
    px = np.cumsum(steps) + 631_205  # ~63120.5
    px = np.maximum(1, px - (px - 631_205) // 8)  # damp excursions (deterministic)
    ts = T0_US + np.cumsum(rng.exponential(DAY_US / n, n)).astype(np.int64)
    return {"ts_us": ts, "price_ticks": px.astype(np.int64), "qty_lots": qty, "is_buy": is_buy}


def write_parquet(cols: dict[str, np.ndarray], dest: Path, rows_per_group: int = 131_072) -> None:
    """Cold-path stand-in for a symbol-day partition (sorted by ts, zstd, like the E07 writer)."""
    table = pa.table({k: pa.array(v) for k, v in cols.items()})
    pq.write_table(table, dest, row_group_size=rows_per_group, compression="zstd")
