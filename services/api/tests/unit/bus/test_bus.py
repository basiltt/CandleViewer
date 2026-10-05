"""Unit tests for `candleviewer.bus.bus.Bus` covering every Gherkin scenario
in the E08-T03 ticket body."""

from __future__ import annotations

import asyncio

import pytest
from structlog.testing import capture_logs

from candleviewer.bus.bus import Bus
from candleviewer.bus.metrics import (
    bus_conflated_total,
    bus_subscriber_lag,
    ingest_queue_full_total,
)
from candleviewer.bus.models import QueuePolicy, StreamInvalidated, Topic

TRADE_TOPIC = Topic(env="demo", domain="of", symbol="BTCUSDT", detail="trade")
BOOK_TOPIC = Topic(env="demo", domain="md", symbol="BTCUSDT", detail="delta")
TICKER_TOPIC = Topic(env="demo", domain="md", symbol="BTCUSDT", detail="ticker")


@pytest.mark.asyncio
async def test_never_drop_scenario_trades_are_never_dropped() -> None:
    """Gherkin: Trades are never dropped."""
    bus = Bus()
    sub = bus.subscribe("oms", "demo.of.BTCUSDT.trade", QueuePolicy.NEVER_DROP, maxsize=1)
    await bus.publish(TRADE_TOPIC, "trade-1")

    before = ingest_queue_full_total.labels(**{"class": "of.trade"})._value.get()
    publish_task = asyncio.create_task(bus.publish(TRADE_TOPIC, "trade-2"))
    await asyncio.sleep(0.01)
    assert not publish_task.done(), "publish must await while the queue is full"

    delivered = await sub.get()
    assert delivered == "trade-1"
    await publish_task
    after = ingest_queue_full_total.labels(**{"class": "of.trade"})._value.get()
    assert after == before + 1

    assert await sub.get() == "trade-2"


@pytest.mark.asyncio
async def test_invalidate_on_full_scenario_book_deltas_invalidate_rather_than_skip() -> None:
    """Gherkin: Book deltas invalidate rather than skip."""
    bus = Bus()
    sub = bus.subscribe("book", "demo.md.BTCUSDT.delta", QueuePolicy.INVALIDATE_ON_FULL, maxsize=1)
    await bus.publish(BOOK_TOPIC, "delta-1")
    await bus.publish(BOOK_TOPIC, "delta-2")  # queue now full -> invalidate

    received = await sub.get()
    assert isinstance(received, StreamInvalidated)
    assert received.reason_code == "queue_overflow"
    assert received.topic == BOOK_TOPIC.key
    assert sub.qsize() == 0, "no partial sequence must remain queued behind the marker"


@pytest.mark.asyncio
async def test_conflate_latest_scenario_state_topics_conflate() -> None:
    """Gherkin: State topics conflate."""
    bus = Bus()
    sub = bus.subscribe(
        "watchlist", "demo.md.BTCUSDT.ticker", QueuePolicy.CONFLATE_LATEST, maxsize=1
    )

    before = bus_conflated_total.labels(topic_class="md.ticker")._value.get()
    for i in range(50):
        await bus.publish(TICKER_TOPIC, f"ticker-{i}")
    after = bus_conflated_total.labels(topic_class="md.ticker")._value.get()

    assert after - before == 49
    assert sub.qsize() == 1
    assert await sub.get() == "ticker-49"


@pytest.mark.asyncio
async def test_conflate_latest_keeps_newest_only_even_with_large_maxsize() -> None:
    """Regression: a paused CONFLATE_LATEST subscriber with a large maxsize
    must not accumulate a backlog — every publish collapses the queue down
    to just the newest event, well before the queue is ever `full()`."""
    bus = Bus()
    sub = bus.subscribe(
        "watchlist", "demo.md.BTCUSDT.ticker", QueuePolicy.CONFLATE_LATEST, maxsize=4096
    )

    for i in range(50):
        await bus.publish(TICKER_TOPIC, f"ticker-{i}")

    assert sub.qsize() == 1, "queue must never grow past 1 item under CONFLATE_LATEST"
    assert await sub.get() == "ticker-49"


@pytest.mark.asyncio
async def test_slow_consumer_scenario_is_named_not_guessed() -> None:
    """Gherkin: Slow consumer is named, not guessed."""
    # CONFLATE_LATEST keeps newest-only (depth is always <=1 regardless of
    # maxsize), so the lag threshold must be 1 for this scenario to fire.
    bus = Bus()
    bus.subscribe(
        "footprint",
        "demo.of.BTCUSDT.trade",
        QueuePolicy.CONFLATE_LATEST,
        maxsize=100,
        lag_warn_threshold=1,
    )
    with capture_logs() as logs:
        for i in range(3):
            await bus.publish(TRADE_TOPIC, f"t{i}")

    warnings = [e for e in logs if e["log_level"] == "warning"]
    assert warnings, "a structured warning must be logged once the lag threshold is crossed"
    assert warnings[-1]["subscriber"] == "footprint"
    assert warnings[-1]["topic"] == TRADE_TOPIC.key
    assert bus_subscriber_lag.labels(subscriber="footprint")._value.get() >= 1


@pytest.mark.asyncio
async def test_drain_scenario_shutdown_loses_nothing_that_matters() -> None:
    """Gherkin: Shutdown loses nothing that matters."""
    bus = Bus()
    sub = bus.subscribe("oms", "demo.of.BTCUSDT.trade", QueuePolicy.NEVER_DROP, maxsize=10)
    for i in range(5):
        await bus.publish(TRADE_TOPIC, f"t{i}")

    async def consume_all() -> None:
        for _ in range(5):
            await sub.get()

    consumer = asyncio.create_task(consume_all())
    outstanding = await bus.drain(grace_s=5.0)
    await consumer

    assert outstanding == {}
    assert sub.qsize() == 0


@pytest.mark.asyncio
async def test_drain_reports_outstanding_when_grace_period_expires() -> None:
    bus = Bus()
    sub = bus.subscribe("oms", "demo.of.BTCUSDT.trade", QueuePolicy.NEVER_DROP, maxsize=10)
    await bus.publish(TRADE_TOPIC, "t0")

    outstanding = await bus.drain(grace_s=0.01)

    assert outstanding == {"oms": 1}
    assert sub.qsize() == 1


@pytest.mark.asyncio
async def test_drain_stops_accepting_new_publishes() -> None:
    from candleviewer.bus.errors import BusShuttingDownError

    bus = Bus()
    bus.subscribe("oms", "demo.of.BTCUSDT.trade", QueuePolicy.NEVER_DROP)
    await bus.drain(grace_s=0.01)

    with pytest.raises(BusShuttingDownError):
        await bus.publish(TRADE_TOPIC, "late")
