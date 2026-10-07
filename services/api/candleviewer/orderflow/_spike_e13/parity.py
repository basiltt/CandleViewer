"""E13-K01 SPIKE parity (throwaway): Python stream + numpy kernels vs TS-kernel dump.

Bars are re-derived on the Python side from the recorded fixture strings via Decimal (boundary),
NOT from the TS dump, so the comparison includes the boundary conversion.
"""

from __future__ import annotations

import json
import math
import sys
from decimal import Decimal
from pathlib import Path

from .kernels import NP, STREAM, Bar, densify, from_decimal

ROOT = Path(__file__).resolve().parents[5]


def recorded() -> list[Bar]:
    m: dict[int, Bar] = {}
    for p in range(3):
        j = json.loads((ROOT / f"packages/fixtures/bybit/2026-10-05/rest/kline_BTCUSDT_1_page{p}.json").read_text("utf-8"))
        for r in j["result"]["list"]:
            m[int(r[0])] = from_decimal(int(r[0]), *(Decimal(x) for x in r[1:6]))
    bars = [m[k] for k in sorted(m)]
    return densify([b for i, b in enumerate(bars) if i < 200 or i >= 215])


def dev(ts: list[float | None], py: list[float]) -> tuple[float, float, int, int, bool]:
    ma = mr = 0.0
    bits = 0
    for a, b in zip(ts, py, strict=True):
        a_ = math.nan if a is None else a
        b_ = float(b)
        if math.isnan(a_) or math.isnan(b_):
            if math.isnan(a_) != math.isnan(b_):
                return math.inf, math.inf, -1, len(py), False
            continue
        if a_ != b_:
            bits += 1
        d = abs(a_ - b_)
        ma = max(ma, d)
        mr = max(mr, d / max(1.0, abs(a_)))
    return ma, mr, bits, len(py), mr <= 1e-8


def main() -> None:
    dump = json.loads(Path(sys.argv[1]).read_text("utf-8"))
    for setname in ("recorded", "synthetic100k"):
        ts = dump[setname]["series"]
        if setname == "recorded":
            bars = recorded()
            assert [b.t for b in bars] == [b["t"] for b in dump["recorded"]["bars"]]
        else:
            bars = [Bar(b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]) for b in dump[setname]["bars"]]
        print(f"## {setname}: {len(bars)} bars")
        for name in STREAM:
            for form, fn in (("stream", STREAM[name]), ("numpy", NP.get(name))):
                if fn is None:
                    continue
                for s, arr in fn(bars).items():
                    ma, mr, nb, n, ok = dev(ts[s], list(arr))
                    print(f"{form:6} {s:16} max_abs={ma:.3e} max_rel={mr:.3e} non_identical={nb}/{n} eps_ok={ok}")


if __name__ == "__main__":
    main()
