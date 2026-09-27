"""Wildcard subscription resolution and per-topic FIFO ordering tests for
`candleviewer.bus.bus.Bus`."""

from __future__ import annotations

import pytest

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, Topic

BTC_TRADE = Topic(env="demo", domain="of", symbol="BTCUSDT", detail="trade")
ETH_TRADE = Topic(env="demo", domain="of", symbol="ETHUSDT", detail="trade")


@pytest.mark.asyncio
async def test_wildcard_subscription_receives_every_matching_symbol() -> None:
    bus = Bus()
    sub = bus.subscribe("all-trades", "demo.of.*.trade", QueuePolicy.NEVER_DROP)

    await bus.publish(BTC_TRADE, "btc-1")
    await bus.publish(ETH_TRADE, "eth-1")

    assert await sub.get() == "btc-1"
    assert await sub.get() == "eth-1"


@pytest.mark.asyncio
async def test_non_matching_subscription_receives_nothing() -> None:
    bus = Bus()
    sub = bus.subscribe("oms-only", "demo.oms.*", QueuePolicy.NEVER_DROP)

    await bus.publish(BTC_TRADE, "btc-1")

    assert sub.qsize() == 0


@pytest.mark.asyncio
async def test_fifo_ordering_per_subscriber_for_single_topic() -> None:
    """Deterministic ordering guarantee: single producer per topic, FIFO per
    subscriber (§ Technical notes / design)."""
    bus = Bus()
    sub = bus.subscribe("oms", "demo.of.BTCUSDT.trade", QueuePolicy.NEVER_DROP)

    for i in range(20):
        await bus.publish(BTC_TRADE, i)

    received = [await sub.get() for _ in range(20)]
    assert received == list(range(20))


@pytest.mark.asyncio
async def test_subscribe_after_publish_new_subscriber_sees_future_events() -> None:
    """The resolved-subscriber cache must not stale-hide a subscriber added
    after an earlier publish to the same topic."""
    bus = Bus()
    await bus.publish(BTC_TRADE, "before")  # no subscribers yet
    sub = bus.subscribe("late", "demo.of.BTCUSDT.trade", QueuePolicy.NEVER_DROP)
    await bus.publish(BTC_TRADE, "after")

    assert await sub.get() == "after"


@pytest.mark.asyncio
async def test_multiple_subscribers_each_get_independent_fifo_copies() -> None:
    bus = Bus()
    sub_a = bus.subscribe("a", "demo.of.*.trade", QueuePolicy.NEVER_DROP)
    sub_b = bus.subscribe("b", "demo.of.*.trade", QueuePolicy.NEVER_DROP)

    await bus.publish(BTC_TRADE, "x")

    assert await sub_a.get() == "x"
    assert await sub_b.get() == "x"
