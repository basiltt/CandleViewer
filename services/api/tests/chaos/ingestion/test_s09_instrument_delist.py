"""Scenario 9 - instrument delists mid-session. C-13.6 #1 (topic teardown).

`rest/instruments_after.json` (recorded corpus) flips LUNAUSDT to `Closed`.
Declared: the catalogue refresh marks it non-tradable, `acquire` refuses it
from then on (`UnknownSymbolError` -> the UI's delisted/paused state), and
when demand is released the topic is unsubscribed - no resubscribe loop
against a symbol that will never publish again; the other symbol is untouched.
"""

from __future__ import annotations

import pytest

from candleviewer.ingestion.ticker_stream import UnknownSymbolError
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig

pytestmark = pytest.mark.chaos

DEAD, ALIVE = "LUNAUSDT", "BTCUSDT"
DEAD_TOPICS = {f"orderbook.200.{DEAD}", f"publicTrade.{DEAD}"}
LOOP_WINDOW_S = 60.0


async def _two_symbol_rig() -> tuple[Rig, Feeder]:
    rig = Rig(seed=9, symbols=(ALIVE, DEAD))
    await rig.start()
    feed = Feeder(rig.ex, books=(ALIVE,), trades={ALIVE: ALIVE, DEAD: "SOLUSDT"})
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    await feed.run(3.0)
    return rig, feed


def _subs(rig: Rig) -> list[str]:
    return [a for s in rig.ex.sockets for m in s.sent if m["op"] == "subscribe" for a in m["args"]]


async def test_s09_delist_marks_symbol_unlisted_and_refuses_new_demand() -> None:
    rig, _feed = await _two_symbol_rig()
    try:
        assert rig.is_listed(DEAD)
        rig.ex.inject(Fault(FaultKind.DELIST, symbol=DEAD))
        await rig.call(rig.instruments.refresh_now())
        assert not rig.is_listed(DEAD)  # the UI renders "delisted / paused"
        assert rig.is_listed(ALIVE)
        with pytest.raises(UnknownSymbolError):
            rig.trades.acquire("chart-2", DEAD)
        with pytest.raises(UnknownSymbolError):
            rig.books.acquire("chart-2", DEAD)
    finally:
        await rig.stop()


async def test_s09_release_after_delist_tears_topics_down() -> None:
    rig, feed = await _two_symbol_rig()
    try:
        rig.ex.inject(Fault(FaultKind.DELIST, symbol=DEAD))
        await rig.call(rig.instruments.refresh_now())
        rig.trades.release("chaos", DEAD)
        rig.books.release("chaos", DEAD)
        await feed.run(31.0)  # past the 30 s demand grace
        rig.trades.sync()
        rig.books.sync()
        await rig.clock.run_until(
            lambda: rig.ws.state() == "open", within_s=35, what="reopen after release"
        )
        await feed.run(1.0)
        live_topics = rig.ex.live_sockets()[0].topics
        assert not (live_topics & DEAD_TOPICS), live_topics
        assert {f"orderbook.200.{ALIVE}", f"publicTrade.{ALIVE}"} <= live_topics
    finally:
        await rig.stop()


async def test_s09_silent_delisted_topic_is_not_resubscribed_in_a_loop() -> None:
    rig, feed = await _two_symbol_rig()
    try:
        rig.ex.inject(Fault(FaultKind.DELIST, symbol=DEAD))
        await rig.call(rig.instruments.refresh_now())
        before = _subs(rig).count(f"orderbook.200.{DEAD}")
        await feed.run(LOOP_WINDOW_S)
        resubs = _subs(rig).count(f"orderbook.200.{DEAD}") - before
        # Bounded by the 250 ms -> 30 s resync backoff: never one per tick.
        assert resubs <= 8, f"{resubs} resubscribes to a delisted book in {LOOP_WINDOW_S}s"
    finally:
        await rig.stop()


async def test_s09_delist_tears_down_held_subscriptions_without_a_release() -> None:
    rig, feed = await _two_symbol_rig()
    try:
        rig.ex.inject(Fault(FaultKind.DELIST, symbol=DEAD))
        await rig.call(rig.instruments.refresh_now())
        await feed.run(5.0)
        assert not (rig.ex.live_sockets()[0].topics & DEAD_TOPICS)
    finally:
        await rig.stop()
