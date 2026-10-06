"""Scenario 10 - bus backpressure from a deliberately slow consumer. C-13.6 #11
(ingestion/bus side; the client-WS-gateway half is E17).

Declared, per queue policy, while the real ingest path publishes recorded data:
* NEVER_DROP: a full queue makes the publisher wait (`ingest_queue_full_total`)
  - nothing lost - and the slow-consumer warning names the subscriber;
* INVALIDATE_ON_FULL: the queue is flushed and a `StreamInvalidated` marker is
  delivered (`bus_stream_invalidated_total`), so the consumer must resnapshot;
* CONFLATE_LATEST: the consumer only ever holds the newest event.
Isolation (06 §6.1): a slow conflated/invalidating consumer never stalls other
symbols' publication.
"""

from __future__ import annotations

import itertools

import pytest
from structlog.testing import capture_logs

from candleviewer.bus.metrics import bus_stream_invalidated_total, ingest_queue_full_total
from candleviewer.bus.models import QueuePolicy, StreamInvalidated
from candleviewer.exchange.base.models import BookDelta, BookSnapshot
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig, metric

pytestmark = pytest.mark.chaos

SLOW_MAX = 8


async def _live(rig: Rig) -> Feeder:
    feed = Feeder(rig.ex)
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    return feed


async def test_s10_invalidate_on_full_marks_the_stream_and_ingest_keeps_flowing(rig: Rig) -> None:
    slow = rig.bus.subscribe("slow-dom", "live.md.BTCUSDT.book", QueuePolicy.INVALIDATE_ON_FULL,
                             maxsize=SLOW_MAX)  # fmt: skip
    before = metric(bus_stream_invalidated_total, topic_class="md.book")
    feed = await _live(rig)
    await feed.run(3.0)  # ~30 book events into an 8-slot queue nobody drains
    items = [slow.get_nowait() for _ in range(slow.qsize())]
    assert any(isinstance(i, StreamInvalidated) for i in items)
    assert metric(bus_stream_invalidated_total, topic_class="md.book") > before
    ui = rig.observe().book_events
    assert sum(isinstance(e, BookDelta) for e in ui) >= 20  # the fast path never waited


async def test_s10_conflate_latest_keeps_only_the_newest(rig: Rig) -> None:
    slow = rig.bus.subscribe("slow-ticker-panel", "live.md.BTCUSDT.book",
                             QueuePolicy.CONFLATE_LATEST, maxsize=SLOW_MAX)  # fmt: skip
    feed = await _live(rig)
    await feed.run(3.0)
    assert slow.qsize() == 1
    newest = slow.get_nowait()
    assert isinstance(newest, BookDelta | BookSnapshot)
    assert newest.update_id == rig.ex.books["orderbook.200.BTCUSDT"].u


async def test_s10_never_drop_backpressures_and_names_the_slow_subscriber(rig: Rig) -> None:
    slow = rig.bus.subscribe("slow-recorder", "live.md.BTCUSDT.book", QueuePolicy.NEVER_DROP,
                             maxsize=SLOW_MAX, lag_warn_threshold=4)  # fmt: skip
    full = metric(ingest_queue_full_total, **{"class": "md.book"})
    feed = await _live(rig)
    with capture_logs() as logs:
        await feed.run(2.0)
    assert metric(ingest_queue_full_total, **{"class": "md.book"}) > full  # publisher waited
    lagging = [e for e in logs if e.get("event") == "bus subscriber lagging"]
    assert lagging and lagging[0]["subscriber"] == "slow-recorder"
    drained: list[object] = []
    while slow.qsize():  # the consumer catches up: nothing was dropped on the way
        drained.append(slow.get_nowait())
        await rig.clock.settle()
    ids = [e.update_id for e in drained if isinstance(e, BookDelta)]
    assert ids == sorted(ids) and len(ids) == len(set(ids))
    assert all(b == a + 1 for a, b in itertools.pairwise(ids))


@pytest.mark.xfail(strict=True, reason="#1916: one NEVER_DROP stall freezes the shared pump")
async def test_s10_slow_never_drop_consumer_does_not_starve_other_symbols() -> None:
    rig = Rig(seed=10, symbols=("BTCUSDT", "ETHUSDT"))
    await rig.start()
    try:
        rig.bus.subscribe("slow-btc", "live.md.BTCUSDT.book", QueuePolicy.NEVER_DROP, maxsize=4)
        feed = Feeder(rig.ex, trades={"BTCUSDT": "BTCUSDT", "ETHUSDT": "ETHUSDT"})
        await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
        await feed.run(10.0)
        eth = [t for t in rig.observe().trades if getattr(t, "symbol", "") == "ETHUSDT"]
        assert len(eth) >= len(rig.ex.trades.prints["ETHUSDT"]) - 2, "ETH starved by BTC"
        assert len(rig.ex.sockets) == 1, "a local slow consumer recycled the exchange socket"
    finally:
        await rig.stop()
