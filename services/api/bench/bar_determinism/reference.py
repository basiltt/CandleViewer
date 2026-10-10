"""Independent reference bar builders: the comparison oracle of the E12-T04 harness.

Written from the specification text ONLY (`docs/plan/24-internal-schemas.md` §3.1 bar model,
§3.3 per-kind rules incl. the "shipped behaviour" paragraphs, §3.4 invariants, ADR-0033 for
renko) and deliberately NOT from `candleviewer/bars/*`: no shared helper, no draft accumulator,
no incremental state. Every bar is a plain list of the trade parts it holds; fields are
recomputed from that list. It is naive and slow on purpose — readability is the point.

Spec rules encoded here (one line each, so a reviewer can check them against the text):
- fields: open/close = first/last part in event order `(ts_event, seq)`; high/low = extremes;
  volume = buy + sell; delta = buy - sell; min/max_delta = extremes of the running cumulative
  delta after each part in ARRIVAL order (24 §3.3 / #1991); turnover = sum(px * qty);
  vwap = turnover / volume rounded half-even to 8 dp, `open` when volume is 0 (BI-6).
- time: bucket `floor((ts - anchor) / step) * step + anchor`; a trade in an earlier bucket
  amends that bar if it closed <= 60 s before the watermark, else it is dropped (also dropped
  when its bucket has no bar); `gap_before` when the previous bar's end != this bar's start.
- tick: closes after exactly `tick_count` trade events. Late trades join the open bar.
- volume: closes at exactly the threshold; an overshooting trade is split, the remainder opens
  the next bar (same px/ts/side); every bar holding a part counts the trade once.
- range: closes when `high - low >= width` (inclusive); the next bar opens at that close but is
  created by the next trade (so H/L include the carried open); `gap_before` after a closing
  span `>= 2 * width`. Never synthesises intermediate bars.
- delta: closes when `|delta| >= threshold`, never split.
- renko: Decimal brick grid from the first price; k whole bricks in the trend direction emit k
  bricks; against it, `n >= R` bricks emit `n - (R - 1)` bricks starting `R - 1` bricks back;
  all volume/trades of the run go to the LAST brick, the others are flat zero-volume bricks;
  the unfinished brick is an open bar from the anchor to the last price. Wicks (optional):
  the run's extreme prices extend the first brick's trailing side and the last brick's
  leading side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal

from candleviewer.bars.models import Bar, BarSpec
from candleviewer.exchange.base.models import TradeEvent

_Q8 = Decimal("0.00000001")
LATE_WINDOW_US = 60 * 1_000_000
DAY_US = 86_400 * 1_000_000


@dataclass
class Part:
    ts: int
    seq: int
    px: Decimal
    qty: Decimal
    buy: bool


@dataclass
class RefBar:
    index: int
    parts: list[Part] = field(default_factory=list)
    start: int | None = None  # time bars: bucket start / end
    end: int | None = None
    pinned_open: Decimal | None = None  # range bars: carried open
    gap_before: bool = False
    closed: bool = False


@dataclass
class RefResult:
    bars: list[Bar]
    dropped_qty: Decimal = Decimal(0)
    dropped: int = 0


def _part(t: TradeEvent, qty: Decimal | None = None) -> Part:
    return Part(t.ts_event, t.seq, t.price, t.qty if qty is None else qty, t.side == "buy")


def materialise(spec: BarSpec, symbol: str, rb: RefBar) -> Bar:
    """Recompute every `Bar` field from the parts the bar holds."""
    ps = rb.parts
    by_event = sorted(ps, key=lambda p: (p.ts, p.seq))
    prices = [p.px for p in ps]
    o = rb.pinned_open if rb.pinned_open is not None else by_event[0].px
    if rb.pinned_open is not None:
        prices.append(rb.pinned_open)
    buy = sum((p.qty for p in ps if p.buy), Decimal(0))
    sell = sum((p.qty for p in ps if not p.buy), Decimal(0))
    path, running = [], Decimal(0)
    for p in ps:
        running += p.qty if p.buy else -p.qty
        path.append(running)
    turnover = sum((p.px * p.qty for p in ps), Decimal(0))
    vol = buy + sell
    vwap = (turnover / vol).quantize(_Q8, ROUND_HALF_EVEN) if vol else o
    return Bar.model_construct(
        spec_hash=spec.spec_hash,
        symbol=symbol,
        index=rb.index,
        open_time=rb.start if rb.start is not None else by_event[0].ts,
        close_time=rb.end if rb.end is not None else by_event[-1].ts,
        open=o,
        high=max(prices),
        low=min(prices),
        close=by_event[-1].px,
        volume=vol,
        buy_volume=buy,
        sell_volume=sell,
        delta=buy - sell,
        min_delta=min(path),
        max_delta=max(path),
        trade_count=len(ps),
        turnover=turnover,
        vwap=vwap,
        closed=rb.closed,
        partial=rb.index == 0,
        gap_before=rb.gap_before,
        synthetic=False,
    )


def _time(spec: BarSpec, symbol: str, tape: list[TradeEvent]) -> RefResult:
    if not spec.align_to_epoch:
        raise NotImplementedError("the reference covers epoch-aligned time bars only")
    step = int(spec.param_value) * 1000
    anchor = spec.session_anchor_utc_min * 60 * 1_000_000
    bars: list[RefBar] = []
    by_start: dict[int, RefBar] = {}
    res = RefResult([])
    watermark = None
    for t in tape:
        ts = t.ts_event
        watermark = ts if watermark is None else max(watermark, ts)
        start = (ts - anchor) // step * step + anchor
        home = by_start.get(start)
        if home is not None:
            if not home.closed or watermark - (start + step) <= LATE_WINDOW_US:
                home.parts.append(_part(t))
                continue
        elif not bars or start > (bars[-1].start or 0):
            if bars:
                bars[-1].closed = True
            gap = bool(bars) and bars[-1].end != start
            bars.append(RefBar(len(bars), [_part(t)], start, start + step, gap_before=gap))
            by_start[start] = bars[-1]
            continue
        res.dropped += 1
        res.dropped_qty += t.qty
    if bars:
        bars[-1].closed = True  # the harness always flushes the clock past the last bucket
    res.bars = [materialise(spec, symbol, b) for b in bars]
    return res


def _activity(spec: BarSpec, symbol: str, tape: list[TradeEvent]) -> RefResult:
    """tick / volume / delta: count, quota (split) or |delta| closure; arrival order."""
    bars: list[RefBar] = []
    limit = Decimal(spec.param_value)
    filled = delta = Decimal(0)  # volume / delta of the open bar so far
    for t in tape:
        rest = t.qty
        while True:
            if not bars or bars[-1].closed:
                bars.append(RefBar(len(bars)))
                filled = delta = Decimal(0)
            b = bars[-1]
            if spec.kind == "volume":
                room = limit - filled
                take = rest if rest <= room else room  # only an overshoot is split
                b.parts.append(_part(t, take))
                filled += take
                rest -= take
                b.closed = take == room
                if rest == 0:
                    break
                continue
            b.parts.append(_part(t))
            delta += t.qty if t.side == "buy" else -t.qty
            b.closed = len(b.parts) >= limit if spec.kind == "tick" else abs(delta) >= limit
            break
    return RefResult([materialise(spec, symbol, b) for b in bars])


def _range(spec: BarSpec, symbol: str, tape: list[TradeEvent], tick: Decimal) -> RefResult:
    width = int(spec.param_value) * tick
    bars: list[RefBar] = []
    carry: Decimal | None = None
    gap = False
    hi = lo = Decimal(0)
    for t in tape:
        if not bars or bars[-1].closed:
            bars.append(RefBar(len(bars), pinned_open=carry, gap_before=gap))
            gap = False
            hi = lo = carry if carry is not None else t.price
        b = bars[-1]
        b.parts.append(_part(t))
        hi, lo = max(hi, t.price), min(lo, t.price)
        span = hi - lo
        if span >= width:
            b.closed = True
            carry = max(b.parts, key=lambda p: (p.ts, p.seq)).px
            gap = span >= 2 * width
    return RefResult([materialise(spec, symbol, b) for b in bars])


def _renko(spec: BarSpec, symbol: str, tape: list[TradeEvent], tick: Decimal) -> RefResult:
    w = int(spec.param_value) * tick  # brick size in price units (ADR-0033: fixed, atr:* R2)
    rev = spec.reversal_bricks
    out: list[Bar] = []
    anchor: Decimal | None = None  # close of the last brick (seeded by the first price)
    trend = 0
    run: list[Part] = []

    def brick(o: Decimal, c: Decimal, owner: bool, first: bool, last: bool) -> Bar:
        lo, hi = min(o, c), max(o, c)
        if spec.renko_wick:
            pmin, pmax = min(p.px for p in run), max(p.px for p in run)
            up = c > o
            if first:
                lo, hi = (min(lo, pmin), hi) if up else (lo, max(hi, pmax))
            if last:
                lo, hi = (lo, max(hi, pmax)) if up else (min(lo, pmin), hi)
        base = materialise(spec, symbol, RefBar(len(out), list(run), closed=True))
        shape = {"open": o, "close": c, "high": hi, "low": lo}
        if owner:  # single allocation: the whole run's volume sits on the last brick
            vwap = base.vwap if base.volume else o
            return base.model_copy(update={**shape, "vwap": vwap})
        z = Decimal(0)
        flat = dict.fromkeys(
            ("volume", "buy_volume", "sell_volume", "delta", "min_delta", "max_delta"), z
        )
        return base.model_copy(update={**shape, **flat, "turnover": z, "trade_count": 0, "vwap": o})

    for t in tape:
        anchor = t.price if anchor is None else anchor
        run.append(_part(t))
        moved = int(abs(t.price - anchor) // w)
        sign = 1 if t.price > anchor else -1
        if moved == 0 or (trend == -sign and moved < rev):
            continue
        first_open = anchor
        if trend == -sign:  # reversal: the first R-1 bricks of the move are its cost
            first_open, moved = anchor + sign * (rev - 1) * w, moved - (rev - 1)
        for i in range(moved):
            o = first_open + sign * i * w
            out.append(brick(o, o + sign * w, i == moved - 1, i == 0, i == moved - 1))
        anchor, trend, run = first_open + sign * moved * w, sign, []
    if run and anchor is not None:  # the forming brick: anchor -> last price, open bar
        bar = materialise(spec, symbol, RefBar(len(out), list(run)))
        prices = [q.px for q in run] if spec.renko_wick else [bar.close]
        shape = {"open": anchor, "high": max(anchor, *prices), "low": min(anchor, *prices)}
        out.append(bar.model_copy(update=shape))
    return RefResult(out)


def build(spec: BarSpec, symbol: str, tape: list[TradeEvent], tick: Decimal) -> RefResult:
    """The reference series for `spec` over `tape` (time bars: flushed past the last bucket)."""
    if spec.kind == "time":
        return _time(spec, symbol, tape)
    if spec.kind == "range":
        return _range(spec, symbol, tape, tick)
    if spec.kind == "renko":
        return _renko(spec, symbol, tape, tick)
    return _activity(spec, symbol, tape)
