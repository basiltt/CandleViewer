"""Reference prototypes of the six `24-internal-schemas.md` 3.3 builders (throwaway, spike E12-K01).

Trades are plain ints `(ts_us, price_ticks, qty_lots, is_buy)`. A closed bar is a tuple
`(open_ts, close_ts, o, h, l, c, vol, buy, sell, min_delta, max_delta, n, turnover, allocated)`.
`snapshot()`/`restore()` let BI-5 be property-tested at random cut points.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Bar = tuple[int, int, int, int, int, int, int, int, int, int, int, int, int, bool]
_State = tuple[int, ...]


class _Draft:
    """Mutable intrabar accumulator; `seed` forces the open price (range bars: no gap)."""

    __slots__ = (
        "buy",
        "c",
        "cum",
        "h",
        "l",
        "maxd",
        "mind",
        "n",
        "o",
        "seed",
        "sell",
        "t0",
        "t1",
        "turn",
    )

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed
        self.n = self.o = self.h = self.l = self.c = self.t0 = self.t1 = 0
        self.buy = self.sell = self.cum = self.mind = self.maxd = self.turn = 0

    def add(self, ts: int, px: int, qty: int, is_buy: bool) -> None:
        if self.n == 0:
            self.o = self.h = self.l = self.seed or px
            self.t0 = ts
        if px > self.h:
            self.h = px
        elif px < self.l:
            self.l = px
        self.c = px
        self.t1 = ts
        self.n += 1
        self.turn += px * qty
        if is_buy:
            self.buy += qty
            self.cum += qty
            self.maxd = max(self.maxd, self.cum)
        else:
            self.sell += qty
            self.cum -= qty
            self.mind = min(self.mind, self.cum)

    def bar(self) -> Bar:
        return (
            self.t0,
            self.t1,
            self.o,
            self.h,
            self.l,
            self.c,
            self.buy + self.sell,
            self.buy,
            self.sell,
            self.mind,
            self.maxd,
            self.n,
            self.turn,
            True,
        )

    def state(self) -> _State:
        return (
            self.seed,
            self.n,
            self.o,
            self.h,
            self.l,
            self.c,
            self.t0,
            self.t1,
            self.buy,
            self.sell,
            self.cum,
            self.mind,
            self.maxd,
            self.turn,
        )

    @classmethod
    def load(cls, s: _State) -> _Draft:
        d = cls()
        (
            d.seed,
            d.n,
            d.o,
            d.h,
            d.l,
            d.c,
            d.t0,
            d.t1,
            d.buy,
            d.sell,
            d.cum,
            d.mind,
            d.maxd,
            d.turn,
        ) = s
        return d


class Builder:
    """Base: closed bars are appended to `self.out`."""

    def __init__(self) -> None:
        self.d = _Draft()
        self.out: list[Bar] = []

    def on_trade(self, ts: int, px: int, qty: int, is_buy: bool) -> None:
        raise NotImplementedError

    def finish(self) -> None:
        if self.d.n:
            self.out.append(self.d.bar())
            self.d = _Draft()

    def snapshot(self) -> Any:
        return self.d.state()

    def restore(self, s: Any) -> None:
        self.d = _Draft.load(s)


class TimeBuilder(Builder):
    def __init__(self, interval_us: int) -> None:
        super().__init__()
        self.iv = interval_us
        self.bucket = -1

    def on_trade(self, ts: int, px: int, qty: int, is_buy: bool) -> None:
        b = ts // self.iv
        if b != self.bucket:
            if self.d.n:
                self.out.append(self.d.bar())
                self.d = _Draft()
            self.bucket = b
        self.d.add(ts, px, qty, is_buy)

    def snapshot(self) -> Any:
        return (self.d.state(), self.bucket)

    def restore(self, s: Any) -> None:
        self.d = _Draft.load(s[0])
        self.bucket = s[1]


class TickBuilder(Builder):
    def __init__(self, count: int) -> None:
        super().__init__()
        self.k = count

    def on_trade(self, ts: int, px: int, qty: int, is_buy: bool) -> None:
        self.d.add(ts, px, qty, is_buy)
        if self.d.n >= self.k:
            self.out.append(self.d.bar())
            self.d = _Draft()


class VolumeBuilder(Builder):
    """An overshooting trade is split (3.3); the remainder opens the next bar(s)."""

    def __init__(self, threshold: int) -> None:
        super().__init__()
        self.q = threshold

    def on_trade(self, ts: int, px: int, qty: int, is_buy: bool) -> None:
        room = self.q - (self.d.buy + self.d.sell)
        while qty >= room:
            self.d.add(ts, px, room, is_buy)
            self.out.append(self.d.bar())
            self.d = _Draft()
            qty -= room
            room = self.q
        if qty:
            self.d.add(ts, px, qty, is_buy)


class RangeBuilder(Builder):
    """Closes when high-low >= range; the next bar opens at the closing price (no gap)."""

    def __init__(self, range_ticks: int) -> None:
        super().__init__()
        self.r = range_ticks

    def on_trade(self, ts: int, px: int, qty: int, is_buy: bool) -> None:
        d = self.d
        d.add(ts, px, qty, is_buy)
        if d.h - d.l >= self.r:
            self.out.append(d.bar())
            self.d = _Draft(seed=px)


class DeltaBuilder(Builder):
    """Closes when |cumulative delta| >= threshold; the closing trade is not split (3.3)."""

    def __init__(self, threshold: int) -> None:
        super().__init__()
        self.t = threshold

    def on_trade(self, ts: int, px: int, qty: int, is_buy: bool) -> None:
        d = self.d
        d.add(ts, px, qty, is_buy)
        if abs(d.cum) >= self.t:
            self.out.append(d.bar())
            self.d = _Draft()


class RenkoBuilder(Builder):
    """Fixed brick size in ticks; `rev` bricks against the trend flip direction.

    A trade moving N bricks emits N bricks with the trade's timestamp; volume/trade-count go to the
    LAST brick only (3.3 a). `brick_ticks` is ALWAYS a plain integer here -- ATR bricks are resolved
    to an integer once, at series construction (ADR-0014), so this class never sees `atr:*`.
    """

    def __init__(self, brick_ticks: int, reversal: int = 2) -> None:
        super().__init__()
        self.b = brick_ticks
        self.rev = reversal
        self.close = 0
        self.trend = 0  # 0 = no direction yet, +1 up, -1 down
        self.armed = False

    def on_trade(self, ts: int, px: int, qty: int, is_buy: bool) -> None:
        self.d.add(ts, px, qty, is_buy)
        if not self.armed:
            self.close, self.armed = px, True
            return
        b, t, c = self.b, self.trend, self.close
        if t == 0:
            if px >= c + b:
                self.trend = 1
            elif px <= c - b:
                self.trend = -1
            else:
                return
            self._run(px, ts, c)
        elif (px - c) * t >= b:
            self._run(px, ts, c)
        elif (c - px) * t >= self.rev * b:
            self.trend = -t
            self._run(px, ts, c - t * (self.rev - 1) * b)

    def _run(self, px: int, ts: int, o: int) -> None:
        b, t, d = self.b, self.trend, self.d
        n = (px - o) * t // b
        for i in range(n):
            c = o + t * b
            if i == n - 1:
                full = d.bar()
                self.out.append(
                    (
                        full[0],
                        ts,
                        o,
                        max(o, c),
                        min(o, c),
                        c,
                        full[6],
                        full[7],
                        full[8],
                        full[9],
                        full[10],
                        full[11],
                        full[12],
                        True,
                    )
                )
            else:
                self.out.append((ts, ts, o, max(o, c), min(o, c), c, 0, 0, 0, 0, 0, 0, 0, False))
            o = c
        self.close = o
        self.d = _Draft()

    def snapshot(self) -> Any:
        return (self.d.state(), self.close, self.trend, self.armed)

    def restore(self, s: Any) -> None:
        self.d = _Draft.load(s[0])
        self.close, self.trend, self.armed = s[1], s[2], s[3]


def make(kind: str, param: int) -> Builder:
    """Factory used by the harness (`param` unit depends on kind)."""
    table: dict[str, Callable[[int], Builder]] = {
        "time": TimeBuilder,
        "tick": TickBuilder,
        "volume": VolumeBuilder,
        "range": RangeBuilder,
        "delta": DeltaBuilder,
        "renko": RenkoBuilder,
    }
    return table[kind](param)


KINDS = ("time", "tick", "volume", "range", "delta", "renko")
