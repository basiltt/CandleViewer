"""ATR-brick prototype (Q1): resolve a brick size ONCE from a fixed 1m time series.

`resolve_atr_ticks` is a pure function of (trades in the lookback window, period, multiple, tick);
the result is a plain integer frozen into the series identity, so replay (BI-4) and
`restore(snapshot())` (BI-5) see exactly the same brick size. `drifting_atr_ticks` is the REJECTED
alternative (brick size follows live ATR) kept only to demonstrate the BI-5 failure.
"""

from __future__ import annotations

from collections.abc import Iterable

from .builders import TimeBuilder

MIN_US = 60_000_000


def wilder_atr(bars: list[tuple[int, ...]], period: int) -> list[int]:
    """Wilder ATR in integer ticks*1 (floor-free: carried as rational via x*period scaling)."""
    out: list[int] = []
    atr_num = 0  # ATR * period, integer, avoids float drift
    prev_close = 0
    for i, b in enumerate(bars):
        h, lo, c = b[3], b[4], b[5]
        tr = h - lo if i == 0 else max(h - lo, abs(h - prev_close), abs(lo - prev_close))
        if i < period:
            atr_num += tr  # seed: simple mean of the first `period` TRs
            if i == period - 1:
                out.append(atr_num // period)
        else:
            atr_num = atr_num - atr_num // period + tr
            out.append(atr_num // period)
        prev_close = c
    return out


def one_minute_bars(trades: Iterable[tuple[int, int, int, bool]]) -> list[tuple[int, ...]]:
    b = TimeBuilder(MIN_US)
    for ts, px, q, buy in trades:
        b.on_trade(ts, px, q, buy)
    b.finish()
    return [bar[:14] for bar in b.out]


def resolve_atr_ticks(
    lookback: Iterable[tuple[int, int, int, bool]], period: int = 14, mult_x100: int = 100
) -> int:
    """Frozen brick size: ATR(period) of the last closed 1m bar before series start, x multiple."""
    atrs = wilder_atr(one_minute_bars(lookback), period)
    if not atrs:
        raise ValueError("insufficient warmup: need period+1 closed 1m bars")  # -> 422 path
    return max(1, atrs[-1] * mult_x100 // 100)
