"""E17-K01 deterministic workload generator: the reference-workspace frame stream.

One stream, three encodings (see codecs.py). Seeded; derives book deltas and trade prints from
the recorded corpus at ``CORPUS`` below (the corpus is a documented-shape assembly, not a live
capture - see its README - so rates/sizes below are *modelled*, and the model is stated in the
finding note).

Rates are the 23-ws-protocol 6.1 default throttles for the 4-pane reference workspace
(16.3): bars 250 ms, footprint 250 ms, book.50 50 ms, trades 100 ms; plus the heatmap pane
(500 ms bucket, 6.1.1) in the "extended" workspace.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from wire_codecs import (
    BAR_REC,
    BOOK_REC,
    FP_CELL,
    FP_GROUP,
    HM_COL,
    HM_ROW,
    KIND_BARS,
    KIND_BOOK_DELTA,
    KIND_BOOK_SNAP,
    KIND_FOOTPRINT,
    KIND_HEATMAP,
    KIND_TRADES,
    PRICE_SCALE,
    QTY_SCALE,
    TRADE_REC,
    Frame,
    dec,
    header,
    undec,
)

SEED = 17_001
T0_MS = 1_789_000_000_000
REPO = Path(__file__).resolve().parents[3]
# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
CORPUS = REPO / "packages" / "fixtures" / "bybit" / "2026-10-05" / "ws"

# 23-ws 6.1 default throttles (ms) - the production cadence of each pane's topic.
RATES_MS = {"book50": 50, "trades": 100, "bars": 250, "footprint": 250, "heatmap": 500}
SYMBOL = "BTCUSDT"
FP_CELLS = 400  # ticket: "footprint bar at 400 cells"
HM_ROWS = 512  # ADR-0005 context: "512 floats every 100 ms"; bids[] + asks[] of 512 rows
Q = 10**QTY_SCALE


def _load_book() -> tuple[list[list[str]], list[list[str]], list[tuple[int, int, list[str]]]]:
    """Fixture snapshot (200 levels/side) and the delta size/qty pool."""
    bids: list[list[str]] = []
    asks: list[list[str]] = []
    deltas: list[tuple[int, int, list[str]]] = []
    with (CORPUS / "orderbook_BTCUSDT.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d["type"] == "snapshot" and not bids:
                bids, asks = d["data"]["b"], d["data"]["a"]
            elif d["type"] == "delta":
                sizes = [q for _, q in d["data"]["b"] + d["data"]["a"]]
                deltas.append((len(d["data"]["b"]), len(d["data"]["a"]), sizes))
    return bids, asks, deltas


def _load_trades() -> list[list[dict[str, Any]]]:
    out = []
    with (CORPUS / "clean_publicTrade_BTCUSDT.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            out.append(json.loads(line)["data"])
    return out


def _levels_payload(levels: list[tuple[int, int]]) -> list[list[str]]:
    return [[dec(p, PRICE_SCALE), dec(q, QTY_SCALE)] for p, q in levels]


def _book_body(
    kind: int, bids: list[tuple[int, int]], asks: list[tuple[int, int]], ts: int, xu: int
) -> bytes:
    parts = [header(kind, len(bids) + len(asks), ts)]
    parts += [BOOK_REC.pack(0, p, q) for p, q in bids]
    parts += [BOOK_REC.pack(1, p, q) for p, q in asks]
    if kind == KIND_BOOK_SNAP:
        parts.append(xu.to_bytes(8, "little") + (xu + 1).to_bytes(8, "little"))
    return b"".join(parts)


def _flat_book(bids: list[tuple[int, int]], asks: list[tuple[int, int]]) -> tuple[int, ...]:
    out = [len(bids), len(asks)]
    for p, q in bids + asks:
        out += [p, q]
    return tuple(out)


class BookModel:
    """Depth-N book driven by fixture-derived delta sizes and quantities."""

    def __init__(self, depth: int, rng: random.Random, change_scale: float = 1.0) -> None:
        sb, sa, self.pool = _load_book()
        self.depth, self.rng, self.scale = depth, rng, change_scale
        base_b = round(float(sb[0][0]) * 10)
        base_a = round(float(sa[0][0]) * 10)
        self.bids = {base_b - i: undec(sb[i % len(sb)][1], QTY_SCALE) for i in range(depth)}
        self.asks = {base_a + i: undec(sa[i % len(sa)][1], QTY_SCALE) for i in range(depth)}
        self.cursor = 0
        self.xu = 1

    def snapshot(self, ts: int, seq: int) -> Frame:
        bids = sorted(self.bids.items(), reverse=True)
        asks = sorted(self.asks.items())
        payload = {
            "symbol": SYMBOL, "depth": self.depth, "price_scale": PRICE_SCALE,
            "qty_scale": QTY_SCALE, "xu": self.xu, "xseq": self.xu + 1,
            "bids": _levels_payload(bids), "asks": _levels_payload(asks),
        }  # fmt: skip
        body = _book_body(KIND_BOOK_SNAP, bids, asks, ts, self.xu)
        return Frame("book_snap", f"book.{SYMBOL}.{self.depth}", seq, ts, payload, body,
                     _flat_book(bids, asks))  # fmt: skip

    def delta(self, ts: int, seq: int) -> Frame:
        nb, na, sizes = self.pool[self.cursor % len(self.pool)]
        self.cursor += 1
        nb, na = max(1, round(nb * self.scale)), max(1, round(na * self.scale))
        out_b: dict[int, int] = {}
        out_a: dict[int, int] = {}
        top_b, top_a = max(self.bids), min(self.asks)
        for n, side, book, top, sign in ((nb, out_b, self.bids, top_b, -1),
                                         (na, out_a, self.asks, top_a, 1)):  # fmt: skip
            for _ in range(n):
                px = top + sign * self.rng.randrange(self.depth)
                q = 0 if self.rng.random() < 0.1 else undec(self.rng.choice(sizes), QTY_SCALE)
                book[px] = q
                side[px] = q
        self.xu += 1
        bids = sorted(out_b.items(), reverse=True)
        asks = sorted(out_a.items())
        payload = {"symbol": SYMBOL, "depth": self.depth, "xu": self.xu, "xseq": self.xu + 1,
                   "bids": _levels_payload(bids), "asks": _levels_payload(asks)}  # fmt: skip
        body = _book_body(KIND_BOOK_DELTA, bids, asks, ts, self.xu)
        return Frame("book_delta", f"book.{SYMBOL}.{self.depth}", seq, ts, payload, body,
                     _flat_book(bids, asks))  # fmt: skip


def trades_frame(batch: list[dict[str, Any]], ts: int, seq: int, rng: random.Random) -> Frame:
    recs, items, flat = [], [], [len(batch)]
    base = ts - 100
    for i, t in enumerate(batch):
        p, q = undec(t["p"], PRICE_SCALE), undec(t["v"], QTY_SCALE)
        side = 0 if t["S"] == "Buy" else 1
        off = (i * 100) // max(1, len(batch))
        flags = 1 if t.get("BT") else 0
        recs.append(TRADE_REC.pack(off, p, q, side, flags))
        items.append({"id": t["i"], "ts_ms": base + off, "price": t["p"], "size": t["v"],
                      "side": "buy" if side == 0 else "sell", "is_block_trade": bool(flags),
                      "tick_direction": t["L"]})  # fmt: skip
        flat += [base + off, p, q, side, flags]
    body = header(KIND_TRADES, len(batch), base) + b"".join(recs)
    return Frame("trades", f"trades.{SYMBOL}", seq, ts, {"symbol": SYMBOL, "trades": items},
                 body, tuple(flat))  # fmt: skip


class BarModel:
    """Live 1 m bar updated every 250 ms (a batch of one confirmed=false bar)."""

    def __init__(self, rng: random.Random, price: int) -> None:
        self.rng, self.o = rng, price
        self.h = self.l = self.c = price
        self.v = self.tn = self.tr = self.d = 0
        self.t_open = T0_MS - (T0_MS % 60_000)

    def frame(self, ts: int, seq: int) -> Frame:
        self.c += self.rng.randint(-3, 3)
        self.h, self.l = max(self.h, self.c), min(self.l, self.c)
        dv = self.rng.randint(0, 40_000)
        self.v += dv
        self.tn += dv * self.c // Q
        self.tr += self.rng.randint(0, 12)
        self.d += self.rng.randint(-20_000, 20_000)
        f = (self.t_open, self.o, self.h, self.l, self.c, self.v, self.tn, self.tr, self.d, 0)
        bar = {"t_ms": f[0], "o": dec(f[1], 1), "h": dec(f[2], 1), "l": dec(f[3], 1),
               "c": dec(f[4], 1), "v": dec(f[5], QTY_SCALE), "turnover": dec(f[6], QTY_SCALE),
               "trades": f[7], "confirm": False, "delta": dec(f[8], QTY_SCALE)}  # fmt: skip
        body = header(KIND_BARS, 1, self.t_open) + BAR_REC.pack(0, *f[1:9], 0)
        payload = {"symbol": SYMBOL, "bar_type": "time", "param": "1", "bars": [bar]}
        return Frame("bars", f"bars.{SYMBOL}.time.1", seq, ts, payload, body, (1, *f))


class FootprintModel:
    """Live 5 m footprint bar: 400 cells; each update touches ~15 cells (ongoing auction)."""

    def __init__(self, rng: random.Random, price: int) -> None:
        self.rng = rng
        self.t_open = T0_MS - (T0_MS % 300_000)
        lo = price - FP_CELLS // 2
        self.cells = [[lo + i, rng.randint(0, 60_000), rng.randint(0, 60_000), rng.randint(1, 30)]
                      for i in range(FP_CELLS)]  # fmt: skip

    def frame(self, ts: int, seq: int) -> Frame:
        for _ in range(15):
            c = self.cells[self.rng.randrange(FP_CELLS)]
            c[self.rng.randint(1, 2)] += self.rng.randint(1, 8_000)
            c[3] += 1
        poc = max(range(FP_CELLS), key=lambda i: self.cells[i][1] + self.cells[i][2])
        cells_j, recs, flat = [], [], [1, self.t_open, FP_CELLS]
        for i, (p, b, a, tr) in enumerate(self.cells):
            fl = 8 if i == poc else 0
            cells_j.append({"price": dec(p, 1), "bid_volume": dec(b, QTY_SCALE),
                            "ask_volume": dec(a, QTY_SCALE), "trades": tr,
                            "is_poc": bool(fl)})  # fmt: skip
            recs.append(FP_CELL.pack(p, b, a, tr, fl))
            flat += [p, b, a, tr, fl]
        bar = {"t_ms": self.t_open, "confirm": False, "cells": cells_j}
        payload = {"symbol": SYMBOL, "bar_type": "time", "param": "5", "bars": [bar]}
        body = (header(KIND_FOOTPRINT, 1, self.t_open) + FP_GROUP.pack(0, FP_CELLS)
                + b"".join(recs))  # fmt: skip
        return Frame("footprint", f"footprint.{SYMBOL}.time.5", seq, ts, payload, body,
                     tuple(flat))  # fmt: skip


def heatmap_frame(bk: BookModel, ts: int, seq: int, rng: random.Random) -> Frame:
    """One 500 ms heatmap column: HM_ROWS rows, bids below mid, asks above (other side 0)."""
    mid = (max(bk.bids) + min(bk.asks)) // 2
    pmin, half = mid - HM_ROWS // 2, HM_ROWS // 2
    bids = [rng.randint(0, 80_000) if i < half else 0 for i in range(HM_ROWS)]
    asks = [rng.randint(0, 80_000) if i >= half else 0 for i in range(HM_ROWS)]
    col = {"t_ms": ts, "price_min": dec(pmin, 1), "price_step": "0.1",
           "bids": [b / Q for b in bids], "asks": [a / Q for a in asks]}  # fmt: skip
    payload = {"symbol": SYMBOL, "time_bucket_ms": 500, "depth": 200, "columns": [col]}
    body = (header(KIND_HEATMAP, 1, ts) + HM_COL.pack(0, pmin, 1, HM_ROWS)
            + b"".join(HM_ROW.pack(b, a) for b, a in zip(bids, asks, strict=True)))  # fmt: skip
    flat = [ts, pmin, 1, HM_ROWS]
    for b, a in zip(bids, asks, strict=True):
        flat += [b, a]
    return Frame("heatmap", f"heatmap.{SYMBOL}", seq, ts, payload, body, tuple(flat))


def generate(seconds: int = 60, *, heatmap: bool = True) -> Iterator[Frame]:
    """Yield the workspace frame stream in send order (sorted by timestamp, stable)."""
    rng = random.Random(SEED)
    book = BookModel(50, rng)
    price = (max(book.bids) + min(book.asks)) // 2
    bars, fp = BarModel(rng, price), FootprintModel(rng, price)
    tr_pool = _load_trades()
    seqs: dict[str, int] = {}

    def nxt(key: str) -> int:
        seqs[key] = seqs.get(key, 0) + 1
        return seqs[key]

    yield book.snapshot(T0_MS, nxt("book"))
    events: list[tuple[int, int, str]] = []
    for name, step in RATES_MS.items():
        if name == "heatmap" and not heatmap:
            continue
        for k, t in enumerate(range(0, seconds * 1000, step)):
            events.append((T0_MS + t + step, k, name))
    events.sort(key=lambda e: (e[0], e[2]))
    ti = 0
    for ts, _k, name in events:
        if name == "book50":
            yield book.delta(ts, nxt("book"))
        elif name == "trades":
            batch = tr_pool[ti % len(tr_pool)]
            ti += 1
            yield trades_frame(batch, ts, nxt("trades"), rng)
        elif name == "bars":
            yield bars.frame(ts, nxt("bars"))
        elif name == "footprint":
            yield fp.frame(ts, nxt("fp"))
        else:
            yield heatmap_frame(book, ts, nxt("hm"), rng)


def w2_streams(seconds: int = 30, scale_with_depth: bool = True) -> dict[str, list[Frame]]:
    """book.200 vs book.500 at the 100 ms cadence (W2).

    ``scale_with_depth``: fixture changes are uniform over depth, so changes/frame scale with
    depth (500 -> 2.5x of the fixture's depth-200 delta sizes). ``False`` = same changed-level
    count at both depths (updates concentrated near the touch) - the lower bound.
    """
    out: dict[str, list[Frame]] = {}
    for depth in (50, 200, 500):
        scale = (depth / 200) if scale_with_depth else 1.0
        bk = BookModel(depth, random.Random(SEED + depth), change_scale=scale)
        frames = [bk.snapshot(T0_MS, 1)]
        for i in range(seconds * 10):
            frames.append(bk.delta(T0_MS + (i + 1) * 100, i + 2))
        out[f"book{depth}"] = frames
    return out
