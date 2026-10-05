"""Deterministic generator for `orderbook_BTCUSDT.jsonl` (E08-S05).

Documented exchange v5 `orderbook.200.BTCUSDT` shapes (24-internal-schemas.md 2.2):
one snapshot, then ~3 h of deltas (one frame / 2 s, `u` +1), a `u == 1`
server-reset snapshot, and one deliberate sequence hole. NOT a live capture
(replace with a recorder capture once E16 lands). Run: python tools/fixtures/gen_orderbook.py
"""

from __future__ import annotations

import json
import random
from decimal import Decimal
from pathlib import Path

TICK = Decimal("0.1")
T0 = 1_700_000_000_000
rng = random.Random(8005)  # noqa: S311 - deterministic fixture, not crypto
mid = 63_120_00  # ticks
_OUT = (
    Path(__file__)
    .resolve()
    .parents[2]
    .joinpath("packages", "fixtures", "bybit", "2026-10-05", "ws", "orderbook_BTCUSDT.jsonl")
)


def px(t: int) -> str:
    return str(Decimal(t) * TICK)


def side(lo: int, hi: int) -> dict[int, str]:
    return {t: f"{rng.randint(1, 900) / 100:.3f}" for t in range(lo, hi)}


def frame(typ: str, ts: int, u: int, b: dict[int, str], a: dict[int, str]) -> str:
    data = {"s": "BTCUSDT", "b": [[px(t), q] for t, q in b.items()],
            "a": [[px(t), q] for t, q in a.items()], "u": u, "seq": 7_000_000 + u}  # fmt: skip
    return json.dumps({"topic": "orderbook.200.BTCUSDT", "type": typ, "ts": ts,
                       "data": data, "cts": ts - 3}, separators=(",", ":"))  # fmt: skip


def main() -> None:
    bids = {t: q for t, q in side(mid - 200, mid).items()}
    asks = {t: q for t, q in side(mid + 1, mid + 201).items()}
    out = [frame("snapshot", T0, 1, dict(bids), dict(asks))]
    u, ts = 1, T0
    for i in range(1, 5400):
        ts += 2000
        u += 1
        if i == 2700:
            u += 5  # deliberate hole: engine must resync, never patch
        if i == 4000:  # server restart: u resets to 1 with a fresh snapshot
            u = 1
            out.append(frame("snapshot", ts, u, dict(bids), dict(asks)))
            continue
        db: dict[int, str] = {}
        da: dict[int, str] = {}
        for _ in range(rng.randint(1, 4)):
            t = rng.randint(mid - 200, mid - 1)
            q = (
                "0"
                if rng.random() < 0.3 and len(bids) > 100
                else f"{rng.randint(1, 900) / 100:.3f}"
            )
            db[t] = q
            bids.pop(t, None) if q == "0" else bids.__setitem__(t, q)
            t = rng.randint(mid + 1, mid + 200)
            q = (
                "0"
                if rng.random() < 0.3 and len(asks) > 100
                else f"{rng.randint(1, 900) / 100:.3f}"
            )
            da[t] = q
            asks.pop(t, None) if q == "0" else asks.__setitem__(t, q)
        out.append(frame("delta", ts, u, db, da))
    _OUT.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
