"""Ingest-boundary validation (#1889 / #1890 / #1892).

The E08-X02 acceptance tests (`tests/security/ingestion/*`, PR #1897) are
copied here without their `xfail` so this PR proves its own fix; the rest are
unit tests per rejection reason, hypothesis properties and a zero-false-positive
replay of the recorded corpus.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy
from candleviewer.exchange.base.frame_guard import (
    MAX_FRAME_DEPTH,
    REJECT_REASONS,
    FrameRejectedError,
    check_event_window,
    check_price,
    check_qty,
    json_depth_exceeds,
)
from candleviewer.exchange.base.models import KlineEvent

# nosemgrep: cv-adapter-isolation reason=X02-fix owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame

# nosemgrep: cv-adapter-isolation reason=X02-fix owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.ticker import parse_ticker_frame, ticker_topic

# nosemgrep: cv-adapter-isolation reason=X02-fix owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.trades import parse_trade_frame, trade_topic
from candleviewer.ingestion import service as service_mod
from candleviewer.ingestion.metrics import ingest_rejected_total
from candleviewer.ingestion.rejection import EventWindow, RejectionLog, reason_of
from candleviewer.ingestion.service import IngestionService
from candleviewer.ingestion.ticker_stream import TickerStream
from candleviewer.ingestion.trade_stream import TradeStream
from candleviewer.observability.context import spawn
from candleviewer.orderbook_wiring import BookStream
from tests._corpus import TICKS, frames, rest

TS = 1_700_000_000_000
TICK = {"BTCUSDT": Decimal("0.1")}
ASKS = [["100.1", "1"], ["100.2", "2"]]
TRADES = frames("ws/clean_publicTrade_BTCUSDT.jsonl")
TICKERS = frames("ws/tickers_BTCUSDT.jsonl")


def _dump(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"))


def trade(**rec: Any) -> str:
    base: dict[str, Any] = {"s": "BTCUSDT", "i": "t-1", "T": TS, "p": "100.0", "v": "1"}
    base.update({"S": "Buy"}, **rec)
    return _dump({"topic": "publicTrade.BTCUSDT", "ts": TS, "type": "snapshot", "data": [base]})


def book(kind: str, u: int, bids: list[list[str]], asks: list[list[str]]) -> str:
    data = {"s": "BTCUSDT", "b": bids, "a": asks, "u": u, "seq": u}
    return _dump({"topic": "orderbook.50.BTCUSDT", "type": kind, "ts": TS + u, "data": data})


def nested(depth: int) -> str:
    return '{"topic":"publicTrade.BTCUSDT","data":' + "[" * depth + "]" * depth + "}"


def rejected(stream: str, reason: str) -> float:
    value: float = ingest_rejected_total.labels(stream=stream, reason=reason)._value.get()
    return value


class Rig:
    """The E08-X02 in-process harness: the three production streams on one bus."""

    def __init__(self, *, window: EventWindow | None = None) -> None:
        self.bus = Bus()
        self.sub = self.bus.subscribe("x02", "live.md.*.*", QueuePolicy.NEVER_DROP, maxsize=10_000)
        self.resubs: deque[str] = deque(maxlen=64)

        async def resub(topic: str) -> None:
            self.resubs.append(topic)

        common: dict[str, Any] = {
            "bus": self.bus,
            "env": "live",
            "set_desired": lambda _t: None,
            "is_listed": lambda s: s in TICK,
            "touch": lambda _t: None,
            "clock": lambda: 0.0,
            "now_us": lambda: TS * 1000,
        }
        self.trades = TradeStream(
            parse_frame=parse_trade_frame, topic_for=trade_topic, event_window=window, **common
        )
        self.tickers = TickerStream(
            parse_frame=parse_ticker_frame, topic_for=ticker_topic, event_window=window, **common
        )
        self.books = BookStream(
            parse_frame=lambda f: parse_book_frame(f, TICK.get),
            topic_for=book_topic,
            resubscribe=resub,
            default_depth=50,
            **common,
        )
        for s in (self.trades, self.tickers, self.books):
            s.acquire("x02", "BTCUSDT")

    async def feed(self, frame: str) -> None:
        await self.trades.handle_frame(frame)
        await self.tickers.handle_frame(frame)
        await self.books.handle_frame(frame)

    def drain(self) -> list[Any]:
        out: list[Any] = []
        while not self.sub.queue.empty():
            out.append(self.sub.queue.get_nowait())
        return out


async def _live(rig: Rig) -> None:
    await rig.feed(book("snapshot", 1, [["100.0", "1"], ["99.9", "2"]], ASKS))
    assert rig.books.view("BTCUSDT", 50) is not None
    rig.drain()


# ---- E08-X02 acceptance tests (copied from #1897, xfail removed) -------------


async def test_off_tick_price_is_rejected() -> None:  # #1890
    rig = Rig()
    await rig.feed(book("snapshot", 1, [["100.05", "1"], ["100.0", "2"]], ASKS))
    assert rig.books.view("BTCUSDT", 50) is None


async def test_far_future_trade_rejected() -> None:  # #1892
    rig = Rig()
    await rig.feed(trade(T=TS * 1000))
    assert rig.drain() == []


async def test_absurd_trade_price_rejected() -> None:  # #1892
    rig = Rig()
    await rig.feed(trade(p="1e308"))
    assert rig.drain() == []


async def test_negative_or_crossed_ticker_rejected() -> None:  # #1892
    rig = Rig()
    msg = json.loads(TICKERS[0])
    msg["data"].update(lastPrice="-5", bid1Price="10", ask1Price="9")
    await rig.feed(json.dumps(msg))
    assert not [e for e in rig.drain() if type(e).__name__ == "TickerEvent"]


def _kline(**ohlcv: Any) -> dict[str, Any]:
    base = {"open": 5, "high": 9, "low": 1, "close": 5, "volume": 1, "turnover": 1}
    base.update(ohlcv)
    return {
        "event_id": "00000000-0000-0000-0000-000000000001",
        "ts_event": 1,
        "ts_ingest": 1,
        "source": "live",
        "symbol": "BTCUSDT",
        "interval": "1",
        "start": 0,
        "end": 60_000_000,
        **base,
        "confirmed": True,
    }


def test_kline_high_below_low_rejected() -> None:  # #1892
    with pytest.raises(ValueError):
        KlineEvent.model_validate(_kline(high=1, low=9))


async def test_deep_nesting_does_not_kill_pump() -> None:  # #1889
    svc, rig = IngestionService(), Rig()
    svc.attach_trades(rig.trades)
    pump = spawn(svc._pump_frames(), name="x02-pump")
    try:
        svc.offer_frame(nested(5_000))
        svc.offer_frame(TRADES[0])
        for _ in range(5):
            await asyncio.sleep(0)
        assert not pump.done(), repr(pump.exception())
        assert rig.drain(), "pump must keep delivering after a hostile frame"
    finally:
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)


# ---- per-reason unit tests --------------------------------------------------


@pytest.mark.parametrize(
    ("frame", "reason"),
    [
        (trade(p="1e308"), "out_of_bounds"),
        (trade(v="1e13"), "out_of_bounds"),
        (trade(p="-1"), "non_positive"),
        (trade(v="0"), "non_positive"),
        (trade(p="NaN"), "non_finite"),
        (trade(p="abc"), "malformed"),
        (trade(T=TS + 60_000), "ts_future"),
        (trade(T=5_000_000_000_000), "ts_future"),
        (nested(5_000), "depth_limit"),  # parser RecursionError backstop
        (nested(MAX_FRAME_DEPTH + 1), "malformed"),  # parses; shape is wrong
    ],
)
async def test_trade_rejection_reason(frame: str, reason: str) -> None:
    rig = Rig()
    before = rejected("trade", reason)
    await rig.feed(frame)
    assert rig.drain() == []
    assert rejected("trade", reason) == before + 1


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        ({"lastPrice": "-5"}, "non_positive"),
        ({"markPrice": "1e13"}, "out_of_bounds"),
        ({"volume24h": "-1"}, "non_positive"),
        ({"turnover24h": "1e30"}, "out_of_bounds"),
        ({"bid1Price": "10", "ask1Price": "9"}, "crossed"),
        ({"indexPrice": "Infinity"}, "non_finite"),
    ],
)
async def test_ticker_rejection_reason(data: dict[str, str], reason: str) -> None:
    rig = Rig()
    msg = json.loads(TICKERS[0])
    msg["data"].update(data)
    before = rejected("ticker", reason)
    await rig.feed(json.dumps(msg))
    assert not [e for e in rig.drain() if type(e).__name__ == "TickerEvent"]
    assert rejected("ticker", reason) == before + 1


def test_guard_helpers_pass_plausible_values() -> None:
    assert check_price(Decimal("1")) == 1
    assert check_qty(Decimal("0"), allow_zero=True) == 0
    assert check_qty(Decimal("2")) == 2
    assert not json_depth_exceeds("[" * 40 + "]" * 40 + "]" * 5, limit=40)


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        ({"fundingRate": "1e31"}, "out_of_bounds"),
        ({"price24hPcnt": "-1e31"}, "out_of_bounds"),
    ],
)
def test_ticker_signed_field_bounds(data: dict[str, str], reason: str) -> None:
    msg = json.loads(TICKERS[0])
    msg["data"].update(data)
    with pytest.raises(FrameRejectedError) as ei:
        parse_ticker_frame(json.dumps(msg))
    assert ei.value.reason == reason


def test_ticker_negative_rate_is_plausible() -> None:
    msg = json.loads(TICKERS[0])
    msg["data"].update(fundingRate="-0.0005", price24hPcnt="-0.12")
    assert parse_ticker_frame(json.dumps(msg)) is not None


def test_ticker_far_future_envelope_rejected() -> None:
    msg = json.loads(TICKERS[0])
    msg["ts"] = 5_000_000_000_000
    with pytest.raises(FrameRejectedError) as ei:
        parse_ticker_frame(json.dumps(msg))
    assert ei.value.reason == "ts_future"


@pytest.mark.parametrize(
    ("bids", "reason"),
    [
        ([["100.05", "1"]], "off_tick"),
        ([["1e13", "1"]], "out_of_bounds"),
        ([["100.0", "-1"]], "non_positive"),
        ([["-100.0", "1"]], "non_positive"),
        ([["100.0", "NaN"]], "non_finite"),
    ],
)
async def test_book_rejection_reason_and_resync(bids: list[list[str]], reason: str) -> None:
    rig = Rig()
    await _live(rig)
    before = rejected("book", reason)
    await rig.feed(book("delta", 2, bids, []))
    out = rig.drain()
    assert not any(type(o).__name__ == "BookDelta" for o in out)
    assert rejected("book", reason) == before + 1
    assert rig.books.view("BTCUSDT", 50) is None  # C-2.5: dropped, never patched
    statuses = [o for o in out if type(o).__name__ == "BookStatus"]
    assert statuses and statuses[-1].reason == "rejected_frame"
    assert list(rig.resubs) == ["orderbook.50.BTCUSDT"]  # resync requested


def test_book_delete_with_zero_qty_still_parses() -> None:
    ev = parse_book_frame(book("delta", 2, [["100.0", "0"]], []), TICK.get)
    assert ev is not None and ev.bids[0].qty == 0 and ev.bids[0].price_ticks == 1000


def test_book_bad_cts_and_future_cts_rejected() -> None:
    msg = json.loads(book("snapshot", 1, [["100.0", "1"]], ASKS))
    msg["cts"] = "soon"
    with pytest.raises(ValueError, match="cts"):
        parse_book_frame(json.dumps(msg), TICK.get)
    msg["cts"] = msg["ts"] + 60_000
    with pytest.raises(FrameRejectedError) as ei:
        parse_book_frame(json.dumps(msg), TICK.get)
    assert ei.value.reason == "ts_future"


@pytest.mark.parametrize(
    "ohlcv",
    [
        {"high": 1, "low": 9},
        {"open": 10},
        {"close": 0.5},
        {"low": 0, "open": 0, "close": 0},
        {"volume": -1},
        {"turnover": -1},
        {"open": "NaN"},
    ],
)
def test_kline_invariants(ohlcv: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        KlineEvent.model_validate(_kline(**ohlcv))


def test_kline_end_before_start_rejected() -> None:
    with pytest.raises(ValueError):
        KlineEvent.model_validate({**_kline(), "start": 10, "end": 5})


def test_kline_plausible_bar_validates() -> None:
    assert KlineEvent.model_validate(_kline(volume=0, turnover=0)).high == 9


# ---- clock / listing window -------------------------------------------------


def _window(launch_ms: int | None) -> EventWindow:
    return EventWindow(
        lambda: TS * 1000, lambda _s: None if launch_ms is None else launch_ms * 1000
    )


async def test_trade_after_local_clock_rejected() -> None:
    rig = Rig(window=_window(None))
    before = rejected("trade", "ts_future")
    # Envelope stamped in the future too, so only the clock-relative check catches it.
    frame = trade(T=TS + 3_600_000).replace(f'"ts":{TS}', f'"ts":{TS + 3_600_000}')
    await rig.feed(frame)
    assert rig.drain() == []
    assert rejected("trade", "ts_future") == before + 1


async def test_trade_before_listing_rejected() -> None:
    rig = Rig(window=_window(TS + 10 * 86_400_000))
    before = rejected("trade", "ts_past")
    await rig.feed(trade())
    assert rig.drain() == []
    assert rejected("trade", "ts_past") == before + 1
    assert rig.trades.open_gaps() == {}  # nothing published yet: no gap to open


async def test_ticker_before_listing_rejected() -> None:
    rig = Rig(window=_window(TS * 2))
    await rig.feed(TICKERS[0])
    assert not [e for e in rig.drain() if type(e).__name__ == "TickerEvent"]


async def test_window_passes_in_range_events() -> None:
    rig = Rig(window=_window(TS - 86_400_000))
    await rig.feed(trade())
    assert len(rig.drain()) == 1


def test_window_skips_unknown_references() -> None:
    check_event_window(10**18, now_us=None, launch_us=None)


async def test_rejected_trade_after_publish_marks_gap() -> None:
    rig = Rig()
    await rig.feed(trade())
    rig.drain()
    await rig.feed(trade(i="t-2", p="1e308"))
    assert "BTCUSDT" in rig.trades.open_gaps()


# ---- pump supervision (#1889) ----------------------------------------------


class _Boom:
    def __init__(self, exc: BaseException) -> None:
        self.exc, self.calls, self.marked, self.invalidated = exc, 0, [], []

    async def handle_frame(self, frame: str) -> None:
        self.calls += 1
        if frame == "bad":
            raise self.exc

    def mark_gap(self, reason: str, symbol: str | None = None) -> None:
        self.marked.append(reason)

    async def invalidate(self, reason: str) -> None:
        self.invalidated.append(reason)
        raise RuntimeError("invalidate failed")  # the breaker must survive this too


async def _pump(svc: IngestionService, frames_in: list[str]) -> None:
    pump = spawn(svc._pump_frames(), name="pump-test")
    try:
        for f in frames_in:
            svc.offer_frame(f)
        for _ in range(len(frames_in) + 5):
            await asyncio.sleep(0)
        assert not pump.done(), repr(pump.exception())
    finally:
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)


async def test_pump_breaker_trips_resync_not_halt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_mod, "PUMP_BREAKER_TRIPS", 3)
    svc, boom = IngestionService(), _Boom(KeyError("x"))
    svc.trades = boom  # type: ignore[assignment]  # duck-typed stream double
    svc.books = boom  # type: ignore[assignment]  # duck-typed stream double
    before = rejected("pump", "internal_error")
    await _pump(svc, ["bad"] * 7 + ["good"])
    assert svc.pump_breaker_trips == 2
    assert boom.marked == ["pump_breaker"] * 2 and boom.invalidated == ["pump_breaker"] * 2
    assert rejected("pump", "internal_error") >= before + 14 + 2
    assert boom.calls == 16  # every frame still dispatched to both streams


async def test_pump_resets_breaker_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_mod, "PUMP_BREAKER_TRIPS", 3)
    svc, boom = IngestionService(), _Boom(RecursionError())
    svc.tickers = boom  # type: ignore[assignment]  # duck-typed stream double
    await _pump(svc, ["bad", "bad", "good", "bad", "bad", "good"])
    assert svc.pump_breaker_trips == 0


# ---- rejection log ----------------------------------------------------------


def test_reason_mapping_is_bounded() -> None:
    assert reason_of(FrameRejectedError("off_tick", "x")) == "off_tick"
    assert reason_of(RecursionError()) == "depth_limit"
    assert reason_of(ValueError("free text")) == "malformed"
    assert reason_of(KeyError("free text")) == "internal_error"
    assert {"malformed", "depth_limit", "internal_error"} <= REJECT_REASONS


def test_rejection_log_rate_limits_and_never_logs_payload() -> None:
    from structlog.testing import capture_logs

    now = [0.0]
    log = RejectionLog("trade", lambda: now[0])
    with capture_logs() as logs:
        for _ in range(5):
            log.record(ValueError("SECRET-PAYLOAD"))
        now[0] = 11.0
        log.record(ValueError("SECRET-PAYLOAD"))
    assert len(logs) == 2 and logs[1]["suppressed"] == 4
    assert all("SECRET" not in str(r) for r in logs)
    assert all("rejected" in r["event"] for r in logs)


# ---- depth guard ------------------------------------------------------------


@pytest.mark.parametrize("depth", [MAX_FRAME_DEPTH + 1, 5_000])
async def test_pump_rejects_deep_frame_before_any_parser(depth: int) -> None:
    svc, boom = IngestionService(), _Boom(KeyError("never"))
    svc.trades = boom  # type: ignore[assignment]  # duck-typed stream double
    before = rejected("pump", "depth_limit")
    await _pump(svc, [nested(depth)])
    assert boom.calls == 0 and svc.pump_breaker_trips == 0
    assert rejected("pump", "depth_limit") == before + 1


@pytest.mark.parametrize("parse", [parse_ticker_frame, lambda f: parse_book_frame(f, TICK.get)])
def test_parser_recursion_backstop(parse: Any) -> None:
    with pytest.raises(FrameRejectedError) as ei:
        parse(nested(5_000))
    assert ei.value.reason == "depth_limit"


@given(depth=st.integers(min_value=0, max_value=200))
def test_depth_guard_matches_true_depth(depth: int) -> None:
    frame = "[" * depth + "]" * depth
    assert json_depth_exceeds(frame) == (depth > MAX_FRAME_DEPTH)


def test_depth_guard_handles_many_shallow_brackets() -> None:
    assert not json_depth_exceeds("[" + ",".join(["[1]"] * 500) + "]")


# ---- properties -------------------------------------------------------------

_ticks = st.integers(min_value=1, max_value=10**7)


@settings(max_examples=200, deadline=None)
@given(ticks=_ticks, frac=st.integers(min_value=1, max_value=9))
def test_any_off_grid_book_price_rejected(ticks: int, frac: int) -> None:
    price = Decimal(ticks) * Decimal("0.1") + Decimal(frac) / 100
    frame = book("snapshot", 1, [[str(price), "1"]], [])
    with pytest.raises(FrameRejectedError) as ei:
        parse_book_frame(frame, TICK.get)
    assert ei.value.reason == "off_tick" and ei.value.symbol == "BTCUSDT"


@settings(max_examples=200, deadline=None)
@given(ticks=_ticks)
def test_any_on_grid_book_price_maps_exactly(ticks: int) -> None:
    price = Decimal(ticks) * Decimal("0.1")
    ev = parse_book_frame(book("snapshot", 1, [[str(price), "1"]], []), TICK.get)
    assert ev is not None and ev.bids[0].price_ticks == ticks


@settings(max_examples=200, deadline=None)
@given(bid=_ticks, gap=st.integers(min_value=1, max_value=10**6))
def test_any_crossed_ticker_rejected(bid: int, gap: int) -> None:
    msg = json.loads(TICKERS[0])
    msg["data"].update(bid1Price=str(bid + gap), ask1Price=str(bid))
    with pytest.raises(FrameRejectedError) as ei:
        parse_ticker_frame(json.dumps(msg))
    assert ei.value.reason == "crossed"


_EXC = st.sampled_from(
    [ValueError, RecursionError, MemoryError, KeyError, TypeError, OverflowError, RuntimeError]
)


@settings(max_examples=25, deadline=None)
@given(excs=st.lists(_EXC, min_size=1, max_size=40))
async def test_pump_survives_any_exception(excs: list[type[BaseException]]) -> None:
    svc = IngestionService()

    class _Seq:
        def __init__(self) -> None:
            self.it = iter(excs)

        async def handle_frame(self, frame: str) -> None:
            raise next(self.it)()

        def mark_gap(self, reason: str, symbol: str | None = None) -> None:
            return None

    svc.trades = _Seq()  # type: ignore[assignment]  # duck-typed stream double
    await _pump(svc, ["f"] * len(excs))


# ---- zero false positives on the recorded corpus ----------------------------

_CORPUS = [
    "ws/burst_tickers_BTCUSDT.jsonl",
    "ws/clean_publicTrade_BTCUSDT.jsonl",
    "ws/clean_publicTrade_ETHUSDT.jsonl",
    "ws/clean_publicTrade_SOLUSDT.jsonl",
    "ws/gap_orderbook_ETHUSDT.jsonl",
    "ws/orderbook_BTCUSDT.jsonl",
    "ws/publicTrade_BTCUSDT.jsonl",
    "ws/reconnect_publicTrade_ETHUSDT.jsonl",
    "ws/tickers_BTCUSDT.jsonl",
]


@pytest.mark.parametrize("rel", _CORPUS)
def test_recorded_corpus_has_zero_rejections(rel: str) -> None:
    parsed = 0
    for raw in frames(rel):
        for parse in (
            parse_trade_frame,
            parse_ticker_frame,
            lambda f: parse_book_frame(f, TICKS.get),
        ):
            if parse(raw) is not None:  # raises on any (false-positive) rejection
                parsed += 1
    assert parsed > 0


# ---- r2: string-aware depth scan (#1889 review finding 1) -------------------

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ingestion"


def test_depth_scan_not_fooled_by_closing_brackets_in_strings() -> None:
    n = 5000  # string literals full of `]` lowered the old count; real nesting ~5000
    assert json_depth_exceeds('{"x":[' + '"]",[' * n + "]" * n + "]}")


def test_depth_scan_crasher_fixture_rejected() -> None:
    raw = (_FIXTURES / "depth_bypass_string_brackets.frame").read_text(encoding="utf-8")
    assert json_depth_exceeds(raw)


def test_depth_scan_ignores_brackets_in_strings_and_handles_escapes() -> None:
    assert not json_depth_exceeds('{"a":"' + "[" * 100 + '"}', limit=4)
    # an escaped quote does not end the string; an escaped backslash does not escape it.
    assert not json_depth_exceeds('{"a":"\\"' + "[" * 100 + '","b":1}', limit=4)
    assert json_depth_exceeds('{"a":"\\\\"' + "[" * 100, limit=4)


@given(st.text(alphabet='[]{}"\\ab', max_size=200), st.integers(min_value=0, max_value=6))
@settings(max_examples=300, deadline=None)
def test_depth_scan_matches_reference_scanner(frame: str, limit: int) -> None:
    depth, in_s, esc, over = 0, False, False, False
    for ch in frame:
        if in_s:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_s = False
        elif ch == '"':
            in_s = True
        elif ch in "[{":
            depth += 1
            over = over or depth > limit
        elif ch in "]}":
            depth -= 1
    assert json_depth_exceeds(frame, limit) == over


# ---- r2: corpus replay through the clock / launchTime window (finding 4) ----


@pytest.mark.parametrize("rel", _CORPUS)
def test_recorded_corpus_passes_clock_and_launch_window(rel: str) -> None:
    """Fake clock = each frame's envelope time; launchTime from the instruments
    capture. Past events are bounded only by `launchTime - 24h` (§14.2)."""
    launch = {
        i["symbol"]: int(i["launchTime"]) * 1000
        for i in rest("rest/instruments_before.json")["result"]["list"]
    }
    now = {"us": 0}
    window = EventWindow(lambda: now["us"], launch.get)
    checked = 0
    for raw in frames(rel):
        now["us"] = int(json.loads(raw)["ts"]) * 1000
        for parse in (parse_trade_frame, parse_ticker_frame):
            ev = parse(raw)
            if ev is None:
                continue
            for e in ev if isinstance(ev, (list, tuple)) else (ev,):
                window(e.symbol, int(e.ts_event_us))
                checked += 1
    assert checked > 0 or "orderbook" in rel
