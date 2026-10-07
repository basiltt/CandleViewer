"""Property tests for `TimeBarBuilder`: invariants BI-1..BI-6 (24 §3.4) and late-trade rules."""

from __future__ import annotations

import random
from decimal import Decimal
from itertools import pairwise

from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.time_builder import LATE_WINDOW_US, TimeBarBuilder
from candleviewer.exchange.base.models import TradeEvent
from tests.unit.bars._trades import SYM, final_bars, trade

T0 = 1_790_000_000_000_000  # µs, an arbitrary 2026 instant
SPECS = st.sampled_from(
    [
        BarSpec(kind="time", interval_ms=1_000),
        BarSpec(kind="time", interval_ms=60_000),
        BarSpec(kind="time", interval_ms=420_000, session_anchor_utc_min=480),
        BarSpec(kind="time", interval_ms=420_000, align_to_epoch=False, session_anchor_utc_min=7),
    ]
)


@st.composite
def tapes(draw: st.DrawFn) -> list[TradeEvent]:
    """Mostly ordered tapes with occasional backwards jumps (late / out-of-order trades)."""
    n = draw(st.integers(1, 120))
    ts = T0 + draw(st.integers(0, 86_400_000_000))
    out = []
    for i in range(n):
        ts += draw(st.integers(-90_000_000, 200_000_000))
        px = Decimal(draw(st.integers(9_000, 11_000))) / 10
        qty = Decimal(draw(st.integers(1, 5_000))) / 1000
        out.append(trade(ts, px, qty, draw(st.sampled_from(["buy", "sell"])), seq=i))
    return out


def run(spec: BarSpec, tape: list[TradeEvent], clock_every: int = 0) -> list[BarUpdate]:
    b = TimeBarBuilder(spec, SYM)
    out: list[BarUpdate] = []
    for i, t in enumerate(tape):
        out += b.on_trade(t)
        if clock_every and i % clock_every == 0:
            out += b.on_clock(t.ts_event)
    return out


def applied(spec: BarSpec, tape: list[TradeEvent]) -> list[TradeEvent]:
    """Independent model of which trades land in a bar (the late-trade rule of §3.3c)."""
    from candleviewer.bars.time_builder import bucket_bounds

    bars: dict[int, int] = {}  # open_time -> close_time
    cur: int | None = None
    wm, last_close, kept = -(2**63), None, []
    for t in tape:
        ts = t.ts_event
        wm = max(wm, ts)
        s, e = bucket_bounds(spec, ts)
        if cur is not None and s == cur:
            kept.append(t)
            continue
        floor = cur if cur is not None else last_close
        if floor is not None and ts < floor:
            if (
                s in bars
                and bars[s] <= (cur if cur is not None else 2**63)
                and (wm - bars[s] <= LATE_WINDOW_US)
            ):
                kept.append(t)
            continue
        if cur is not None:
            last_close = bars[cur]
        cur, bars[s] = s, e
        kept.append(t)
    return kept


def _check_bar(b: Bar) -> None:
    assert b.delta == b.buy_volume - b.sell_volume  # BI-2
    assert b.volume == b.buy_volume + b.sell_volume
    assert b.min_delta <= b.delta <= b.max_delta  # BI-3
    if b.volume:  # BI-6
        assert b.vwap == (b.turnover / b.volume).quantize(Decimal("1e-8"))
    else:
        assert b.vwap == b.open
    assert b.low <= min(b.open, b.close) and b.high >= max(b.open, b.close)


@settings(max_examples=300, deadline=None)
@given(SPECS, tapes())
def test_invariants_bi1_bi2_bi3_bi6_hold_on_every_emission(
    spec: BarSpec, tape: list[TradeEvent]
) -> None:
    updates = run(spec, tape, clock_every=3)
    for u in updates:
        _check_bar(u.bar)
    bars = final_bars(updates)
    kept = applied(spec, tape)
    assert sum(b.volume for b in bars) == sum(t.qty for t in kept)  # BI-1 (applied trades)
    assert [b.index for b in bars] == list(range(len(bars)))
    assert all(a.close_time <= b.open_time for a, b in pairwise(bars))


@settings(max_examples=200, deadline=None)
@given(SPECS, tapes())
def test_bi3_min_max_delta_are_attained_on_the_path(spec: BarSpec, tape: list[TradeEvent]) -> None:
    ordered = sorted(tape, key=lambda t: t.ts_event)
    for bar in final_bars(run(spec, ordered)):
        path, d = [], Decimal(0)
        for t in ordered:
            if bar.open_time <= t.ts_event < bar.close_time:
                d += t.qty if t.side == "buy" else -t.qty
                path.append(d)
        assert (min(path), max(path)) == (bar.min_delta, bar.max_delta)


@settings(max_examples=200, deadline=None)
@given(SPECS, tapes())
def test_bi1_ordered_tape_conserves_volume_exactly(spec: BarSpec, tape: list[TradeEvent]) -> None:
    ordered = sorted(tape, key=lambda t: t.ts_event)
    bars = final_bars(run(spec, ordered, clock_every=5))
    assert sum(b.volume for b in bars) == sum(t.qty for t in ordered)
    assert sum(b.trade_count for b in bars) == len(ordered)


@settings(max_examples=200, deadline=None)
@given(SPECS, tapes())
def test_bi4_replaying_the_same_tape_yields_identical_bars(
    spec: BarSpec, tape: list[TradeEvent]
) -> None:
    assert run(spec, tape, 4) == run(spec, list(tape), 4)


@settings(max_examples=200, deadline=None)
@given(SPECS, tapes(), st.data())
def test_bi5_restore_snapshot_at_any_cut_matches_uninterrupted_run(
    spec: BarSpec, tape: list[TradeEvent], data: st.DataObject
) -> None:
    cut = data.draw(st.integers(0, len(tape)))
    whole = run(spec, tape, 2)
    first = TimeBarBuilder(spec, SYM)
    out: list[BarUpdate] = []
    for i, t in enumerate(tape[:cut]):
        out += first.on_trade(t)
        if i % 2 == 0:
            out += first.on_clock(t.ts_event)
    resumed = TimeBarBuilder(spec, SYM)
    resumed.restore(first.snapshot())
    for i, t in enumerate(tape[cut:], start=cut):
        out += resumed.on_trade(t)
        if i % 2 == 0:
            out += resumed.on_clock(t.ts_event)
    assert out == whole
    assert resumed.snapshot() == run_state(spec, tape)


def run_state(spec: BarSpec, tape: list[TradeEvent]) -> object:
    b = TimeBarBuilder(spec, SYM)
    for i, t in enumerate(tape):
        b.on_trade(t)
        if i % 2 == 0:
            b.on_clock(t.ts_event)
    return b.snapshot()


def test_bi1_bulk_seeded_tape_conserves_volume() -> None:
    """Seeded bulk run (200 k trades; the 1 M-trade timing run belongs to E12-T04)."""
    rng = random.Random(341)  # noqa: S311 - seeded test data, not crypto
    spec = BarSpec(kind="time", interval_ms=60_000)
    b = TimeBarBuilder(spec, SYM)
    ts, total, out = T0, Decimal(0), []
    for i in range(200_000):
        ts += rng.randrange(0, 2_000_000)
        q = Decimal(rng.randrange(1, 10_000)) / 1000
        total += q
        out.append(b.on_trade(trade(ts, Decimal(rng.randrange(9_000, 11_000)), q, "buy", i))[-1])
    assert sum(b.volume for b in final_bars(out)) == total
