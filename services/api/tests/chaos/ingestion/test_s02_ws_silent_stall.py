"""Scenario 2 - WS silent stall (socket open, no frames). C-13.6 #1.

Declared: the staleness watchdog fires within its 2 s book threshold (+ one
0.5 s check tick), publishes `stale` for the topic (per-panel stale shading,
14-screens principle 4), the chart recycles the socket (`TOPIC_STALE` ->
backing_off), a new socket resubscribes and the book is LIVE again.

#1913 refined the recycle: one silent topic only resubscribes that topic; the
shared socket is recycled once EVERY watched topic is stale, i.e. after the
slowest limit (trades, 10 s) + one check tick. A fully stalled socket therefore
recycles at <= RECYCLE_SLO_S, while the per-topic `stale` signal still fires at 2 s.
"""

from __future__ import annotations

import pytest

from candleviewer.book.models import BookPhase
from candleviewer.ingestion.metrics import ingest_ws_up
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig, metric

pytestmark = pytest.mark.chaos

BOOK_TOPIC = "orderbook.200.BTCUSDT"
STALE_LIMIT_S, CHECK_TICK_S = 2.0, 0.5
DETECT_SLO_S = STALE_LIMIT_S + CHECK_TICK_S
TRADE_LIMIT_S = 10.0
RECYCLE_SLO_S = TRADE_LIMIT_S + CHECK_TICK_S  # all topics stale -> socket recycle
RECOVER_SLO_S = 5.0


async def test_s02_stall_is_detected_within_threshold_and_socket_recycled(rig: Rig) -> None:
    feed = Feeder(rig.ex)
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    await feed.run(3.0)
    assert rig.book_phase() is BookPhase.LIVE
    rig.observe()

    rig.ex.inject(Fault(FaultKind.STALL))
    t0 = rig.clock.now
    while not any(f.state == "stale" and f.topic == BOOK_TOPIC for f in rig.observe().feed):
        assert rig.clock.now - t0 <= DETECT_SLO_S, "watchdog did not fire within threshold"
        await feed.run(0.1)
    detect_s = rig.clock.now - t0
    assert STALE_LIMIT_S <= detect_s <= DETECT_SLO_S
    while not rig.ex.sockets[0].closed:  # recycled, not left half-open
        assert rig.clock.now - t0 <= RECYCLE_SLO_S, "stalled socket not recycled in time"
        await feed.run(0.1)
    assert metric(ingest_ws_up, socket="public") == 0.0

    t1 = rig.clock.now
    while rig.book_phase() is not BookPhase.LIVE or rig.ws.state() != "open":
        assert rig.clock.now - t1 <= RECOVER_SLO_S, "no recovery after stall"
        await feed.run(0.1)
    assert len(rig.ex.live_sockets()) == 1 and rig.ex.live_sockets()[0].conn_id == 2
    states = [f.state for f in rig.observe().feed if f.topic == BOOK_TOPIC]
    assert states[-3:] == ["degraded", "resubscribing", "healthy"]
