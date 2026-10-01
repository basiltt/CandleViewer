"""E08-S04 acceptance scenarios: trade tape (fake clock, recorded-shape fixtures, no network)."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.exchange.bybit.trades import (
    parse_recent_trades,
    parse_trade_frame,
    recent_trades_fetcher,
    trade_topic,
)
from candleviewer.ingestion.metrics import (
    trade_duplicates_suppressed_total,
    trade_gaps_total,
)
from candleviewer.ingestion.ticker_stream import UnknownSymbolError
from candleviewer.ingestion.trade_stream import DedupeRing, GapEvent, TradeStream, merge_ordered
from candleviewer.ingestion.watchdog import FeedHealthEvent

FIX = Path(__file__).parents[2] / "fixtures" / "bybit"
FRAMES = (FIX / "publicTrade_BTCUSDT.jsonl").read_text(encoding="utf-8").splitlines()
RECENT = json.loads((FIX / "recent_trade_BTCUSDT.json").read_text(encoding="utf-8"))
ID = "a0000001-0000-4000-8000-00000000000"


def _val(counter: Any, **labels: str) -> float:
    return float(counter.labels(**labels)._value.get())


class Harness:
    def __init__(self, fetch: Any = None, writer: Any = None, maxsize: int = 100_000) -> None:
        self.bus = Bus()
        self.desired: set[str] = set()
        self.sub = self.bus.subscribe(
            "t", "live.md.*.trade", QueuePolicy.NEVER_DROP, maxsize=maxsize
        )
        self.gaps = self.bus.subscribe("g", "live.md.*.gap", QueuePolicy.NEVER_DROP)
        self.stream = TradeStream(
            bus=self.bus,
            env="live",
            set_desired=self._set,
            parse_frame=parse_trade_frame,
            topic_for=trade_topic,
            is_listed=lambda s: s in ("BTCUSDT", "ETHUSDT"),
            touch=lambda _t: None,
            fetch_recent=fetch,
            tick_size=lambda _s: Decimal("0.10"),
            clock=lambda: 0.0,
            now_us=lambda: 1_700_000_009_500_000,
            writer=writer,
        )
        self.stream.acquire("tape", "BTCUSDT")

    def _set(self, desired: set[str]) -> None:
        self.desired = set(desired)

    def events(self) -> list[TradeEvent]:
        out = []
        while not self.sub.queue.empty():
            out.append(self.sub.queue.get_nowait())
        return out

    def gap_events(self) -> list[GapEvent]:
        out = []
        while not self.gaps.queue.empty():
            out.append(self.gaps.queue.get_nowait())
        return out


async def _recent(_s: str) -> Sequence[TradePrint]:
    return parse_recent_trades("BTCUSDT", RECENT)


async def _reconnect(h: Harness) -> None:
    await h.stream.process_health(FeedHealthEvent("publicTrade.BTCUSDT", "resubscribing", 0.0))


# ---- Scenario: Ingest -------------------------------------------------------
async def test_ingest_normalises_and_publishes_each_print_once() -> None:
    h = Harness()
    assert h.desired == {"publicTrade.BTCUSDT"}
    for f in FRAMES[:2]:
        await h.stream.handle_frame(f)
    ev = h.events()
    assert [e.trade_id for e in ev] == [f"{ID}1", f"{ID}2", f"{ID}3"]
    first = ev[0]
    assert first.ts_event == 1_700_000_000_050_000  # ms -> µs
    assert (first.price, first.qty, first.side) == (Decimal("63120.50"), Decimal("0.010"), "buy")
    assert first.notional == Decimal("63120.50") * Decimal("0.010")
    assert first.price_ticks == 631205
    assert first.source == "live" and [e.seq for e in ev] == [1, 2, 3]
    assert ev[2].is_block_trade is True and first.is_block_trade is False


def test_bybit_S_is_the_taker_side() -> None:
    """Documented fixture: `S`="Buy" = taker lifted the ask; never re-derived from `L`."""
    prints = parse_trade_frame(FRAMES[0])
    assert prints is not None
    assert [(p.trade_id[-1], p.side) for p in prints] == [("1", "buy"), ("2", "sell")]


def test_parser_ignores_other_topics_and_rejects_hostile_payloads() -> None:
    assert parse_trade_frame('{"topic":"tickers.BTCUSDT","data":{}}') is None
    assert parse_trade_frame("not json") is None
    rec = json.loads(FRAMES[0])
    for mutate in (
        lambda r: r["data"][0].__setitem__("i", "x" * 65),
        lambda r: r["data"][0].__setitem__("p", "NaN"),
        lambda r: r["data"][0].__setitem__("v", "-1"),
        lambda r: r["data"][0].__setitem__("S", "Up"),
        lambda r: r.__setitem__("data", [r["data"][0]] * 2001),
        lambda r: r.__setitem__("topic", "publicTrade.bad*"),
    ):
        bad = json.loads(FRAMES[0])
        mutate(bad)
        with pytest.raises(ValueError):
            parse_trade_frame(json.dumps(bad))
    assert rec  # untouched original


async def test_unknown_symbol_cannot_create_topic() -> None:
    h = Harness()
    with pytest.raises(UnknownSymbolError):
        h.stream.acquire("x", "EVIL.*")


async def test_malformed_frame_is_dropped_stream_continues() -> None:
    h = Harness()
    await h.stream.handle_frame('{"topic":"publicTrade.BTCUSDT","data":[{"s":"BTCUSDT"}]}')
    await h.stream.handle_frame(FRAMES[1])
    assert [e.trade_id for e in h.events()] == [f"{ID}3"]


# ---- Scenario: Gap detection and backfill / Backfill overlaps live data ------
async def test_reconnect_records_gap_backfills_and_marks_window() -> None:
    h = Harness(fetch=_recent)
    for f in FRAMES[:2]:
        await h.stream.handle_frame(f)
    h.events()
    await _reconnect(h)
    assert "BTCUSDT" in h.stream.open_gaps()
    before = _val(trade_gaps_total, symbol="BTCUSDT", recovered="true")
    await h.stream.handle_frame(FRAMES[2])
    (gap,) = h.gap_events()
    assert (gap.start_us, gap.end_us, gap.recovered) == (
        1_700_000_000_290_000,
        1_700_000_009_000_000,
        True,
    )
    assert gap.reason == "reconnect" and gap.label() == "Backfilled 22:13:20-22:13:29"
    assert _val(trade_gaps_total, symbol="BTCUSDT", recovered="true") == before + 1
    ev = h.events()
    assert [e.trade_id[-1] for e in ev] == ["4", "5", "6", "7"]
    assert [e.source for e in ev] == ["backfill"] * 3 + ["live"]
    assert h.stream.gaps("BTCUSDT") == [gap]


async def test_backfill_overlap_each_id_once_ordered_never_backwards() -> None:
    h = Harness(fetch=_recent)
    for f in FRAMES[:2]:
        await h.stream.handle_frame(f)
    await _reconnect(h)
    await h.stream.handle_frame(FRAMES[2])
    ev = h.events()
    ids = [e.trade_id for e in ev]
    assert len(ids) == len(set(ids)) == 7
    keys = [(e.ts_event, e.trade_id) for e in ev]
    assert keys[2:] == sorted(keys[2:])  # 5 and 6 share ts 5000 ms -> ordered by trade_id
    assert all(a.ts_event <= b.ts_event for a, b in pairwise(ev) if a.seq > 2)


# ---- Scenario: Duplicate suppression -------------------------------------
async def test_same_trade_id_after_reconnect_ingested_once_and_counted() -> None:
    h = Harness()
    await h.stream.handle_frame(FRAMES[1])
    before = _val(trade_duplicates_suppressed_total, symbol="BTCUSDT")
    await _reconnect(h)
    await h.stream.handle_frame(FRAMES[1])  # replayed after reconnect
    assert [e.trade_id for e in h.events()] == [f"{ID}3"]
    assert _val(trade_duplicates_suppressed_total, symbol="BTCUSDT") == before + 1


def test_dedupe_ring_is_bounded() -> None:
    ring = DedupeRing(capacity=3)
    assert all(ring.add(str(i)) for i in range(5))
    assert len(ring) == 3
    assert not ring.add("4") and ring.add("0")  # evicted oldest is new again


# ---- Scenario: Backfill unavailable ----------------------------------------
@pytest.mark.parametrize("mode", ["rate_limited", "short", "none"])
async def test_backfill_unavailable_leaves_gap_unrecovered_stream_continues(mode: str) -> None:
    async def rate_limited(_s: str) -> Sequence[TradePrint]:
        raise RuntimeError("10006 rate limit")

    async def short(_s: str) -> Sequence[TradePrint]:
        return [p for p in parse_recent_trades("BTCUSDT", RECENT) if p.trade_id[-1] in "67"]

    fetch = {"rate_limited": rate_limited, "short": short, "none": None}[mode]
    h = Harness(fetch=fetch)
    await h.stream.handle_frame(FRAMES[1])
    await _reconnect(h)
    before = _val(trade_gaps_total, symbol="BTCUSDT", recovered="false")
    await h.stream.handle_frame(FRAMES[2])
    (gap,) = h.gap_events()
    assert gap.recovered is False and gap.start_us < gap.end_us
    assert gap.label().startswith("No data ")
    assert _val(trade_gaps_total, symbol="BTCUSDT", recovered="false") == before + 1
    assert h.events()[-1].trade_id == f"{ID}7"  # stream continues


async def test_recent_trades_fetcher_passes_limit_1000() -> None:
    seen: dict[str, Any] = {}

    async def get_public(path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        seen.update(params, path=path)
        return RECENT

    rows = await recent_trades_fetcher(get_public)("BTCUSDT")
    assert seen["limit"] == 1000 and seen["path"] == "/v5/market/recent-trade"
    assert len(rows) == 6 and rows[-1].ts_event_us == 1_700_000_000_050_000


async def test_frame_loss_marks_gap() -> None:
    h = Harness()
    await h.stream.handle_frame(FRAMES[1])
    h.stream.mark_gap("frame_loss", "BTCUSDT")
    await h.stream.handle_frame(FRAMES[2])
    (gap,) = h.gap_events()
    assert gap.reason == "frame_loss" and gap.recovered is False


# ---- Property: any interleaving of live and backfilled prints ----------------
def _p(i: int, ts_ms: int) -> TradePrint:
    one = Decimal("1")
    return TradePrint("BTCUSDT", f"t{i:05d}", ts_ms * 1000, one, one, "buy", False)


def _frame(prints: Sequence[TradePrint]) -> str:
    data = [
        {"T": p.ts_event_us // 1000, "s": p.symbol, "S": "Buy", "v": "1", "p": "1", "i": p.trade_id}
        for p in prints
    ]
    return json.dumps({"topic": "publicTrade.BTCUSDT", "data": data})


@settings(max_examples=60, deadline=None)
@given(
    ts=st.lists(st.integers(1, 50), min_size=2, max_size=40),
    split=st.integers(0, 40),
    picks=st.lists(st.booleans(), min_size=40, max_size=40),
    dupes=st.lists(st.integers(0, 39), max_size=10),
)
def test_property_interleaving_is_duplicate_free_and_ordered(
    ts: list[int], split: int, picks: list[bool], dupes: list[int]
) -> None:
    import asyncio

    tape = [_p(i, t) for i, t in enumerate(sorted(ts))]
    cut = min(split, len(tape) - 1)
    before, after = tape[:cut], tape[cut:]
    page = [p for p, keep in zip(tape, picks, strict=False) if keep]
    replay = [tape[d] for d in dupes if d < len(tape)]

    async def fetch(_s: str) -> Sequence[TradePrint]:
        return page

    async def run() -> list[TradeEvent]:
        h = Harness(fetch=fetch)
        if before:
            await h.stream.handle_frame(_frame(before))
        await _reconnect(h)
        await h.stream.handle_frame(_frame(after))
        if replay:
            await h.stream.handle_frame(_frame(replay))
        return h.events()

    ev = asyncio.run(run())
    ids = [e.trade_id for e in ev]
    assert len(ids) == len(set(ids))
    assert set(ids) >= {p.trade_id for p in tape}
    assert all(a.ts_event <= b.ts_event for a, b in pairwise(ev))


def test_merge_ordered_ties_by_trade_id() -> None:
    a, b = _p(2, 5), _p(1, 5)
    assert merge_ordered([a], [b, a]) == [b, a]


# ---- Scenario: Burst without loss ---------------------------------------
async def test_burst_5000_prints_per_second_no_loss_with_backpressure() -> None:
    import asyncio

    from candleviewer.bus.metrics import ingest_queue_full_total

    h = Harness(maxsize=64)  # slow consumer: queue fills, reader must block, not drop
    h.stream.acquire("tape", "ETHUSDT")
    full_before = _val(ingest_queue_full_total, **{"class": "md.trade"})
    got: list[TradeEvent] = []
    total = 5000

    async def consumer() -> None:
        while len(got) < total:
            got.append(await h.sub.queue.get())
            if len(got) % 100 == 0:
                await asyncio.sleep(0)

    task = asyncio.create_task(consumer())
    lat: list[float] = []
    for b in range(100):  # 100 frames x 50 prints = one second of 5 000 prints
        sym = "BTCUSDT" if b % 2 else "ETHUSDT"
        prints = [_p(b * 50 + i, 1000 + b) for i in range(50)]
        frame = _frame(prints).replace("BTCUSDT", sym)
        t0 = time.perf_counter()
        await h.stream.handle_frame(frame)
        lat.append((time.perf_counter() - t0) / 50)
    await asyncio.wait_for(task, 10)
    assert len(got) == total and len({(e.symbol, e.trade_id) for e in got}) == total
    assert _val(ingest_queue_full_total, **{"class": "md.trade"}) > full_before
    lat.sort()
    assert lat[int(len(lat) * 0.95)] < 0.020  # ingest->bus p95 budget per print


# ---- QuestDB write-behind ---------------------------------------------
class _Writer:
    def __init__(self, fail: bool = False) -> None:
        self.rows: list[TradeEvent] = []
        self.fail = fail

    async def write_trades(self, events: Sequence[TradeEvent]) -> None:
        if self.fail:
            raise OSError("questdb down")
        self.rows.extend(events)


async def test_write_behind_batches_and_survives_writer_failure() -> None:
    w = _Writer()
    h = Harness(writer=w)
    for f in FRAMES[:2]:
        await h.stream.handle_frame(f)
    assert await h.stream.drain_writes() == 3
    assert [e.trade_id[-1] for e in w.rows] == ["1", "2", "3"]
    w.fail = True
    await h.stream.handle_frame(FRAMES[2])
    assert await h.stream.drain_writes() == 1  # logged, not raised


async def test_stalled_writer_never_blocks_reader() -> None:
    from candleviewer.ingestion import trade_stream as ts

    h = Harness(writer=_Writer())
    for i in range(ts.WRITE_QUEUE_MAXSIZE + 10):  # nobody drains: drop-oldest, counted
        await h.stream.handle_frame(_frame([_p(i, 1 + i)]))
    assert h.stream._writes.qsize() == ts.WRITE_QUEUE_MAXSIZE


async def test_lifecycle_health_loop_marks_gap_and_release_unsubscribes() -> None:
    import asyncio

    h = Harness()
    await h.stream.start()
    await h.stream.handle_frame(FRAMES[1])
    from candleviewer.bus.models import Topic

    await h.bus.publish(
        Topic(env="live", domain="health", detail="feed"),
        FeedHealthEvent("publicTrade.BTCUSDT", "degraded", 0.0),
    )
    for _ in range(5):
        await asyncio.sleep(0)
    assert h.stream.open_gaps()["BTCUSDT"][1] == "reconnect"
    await h.stream.stop()
    h.stream.release("tape", "BTCUSDT")
    h.stream._demand._grace = 0.0
    h.stream.sync()
    assert h.desired == set() and h.stream.open_gaps() == {}
    assert h.stream.is_listed("BTCUSDT") and len(h.stream.recent("BTCUSDT")) == 1


async def test_frames_for_unsubscribed_symbol_ignored() -> None:
    h = Harness()
    await h.stream.handle_frame(FRAMES[0].replace("BTCUSDT", "SOLUSDT"))
    await h.stream.handle_frame('{"topic":"tickers.BTCUSDT"}')
    assert h.events() == []
