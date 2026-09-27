"""Property-based test (`docs/plan/28-...` n/a; ticket Test plan): for any
interleaving of publishes and consumer stalls, a NEVER_DROP stream is a
permutation-free, prefix-preserving sequence — i.e. the subscriber always
observes events in publish order and never misses one."""

from __future__ import annotations

import asyncio

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, Topic

TOPIC = Topic(env="demo", domain="of", symbol="BTCUSDT", detail="trade")


async def _run(n_events: int, stall_positions: set[int], maxsize: int) -> list[int]:
    bus = Bus()
    sub = bus.subscribe("oms", "demo.of.BTCUSDT.trade", QueuePolicy.NEVER_DROP, maxsize=maxsize)
    received: list[int] = []

    async def consume() -> None:
        for _ in range(n_events):
            received.append(await sub.get())

    consumer = asyncio.create_task(consume())
    for i in range(n_events):
        if i in stall_positions:
            await asyncio.sleep(0)
        await bus.publish(TOPIC, i)
    await consumer
    return received


@given(
    n_events=st.integers(min_value=1, max_value=30),
    maxsize=st.integers(min_value=1, max_value=8),
    data=st.data(),
)
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_never_drop_stream_is_prefix_preserving_under_any_stall_pattern(
    n_events: int, maxsize: int, data: st.DataObject
) -> None:
    stall_positions = data.draw(
        st.sets(st.integers(min_value=0, max_value=n_events - 1), max_size=n_events)
    )

    received = asyncio.run(_run(n_events, stall_positions, maxsize))

    assert received == list(range(n_events)), (
        "every event must be delivered exactly once, in publish order, "
        "regardless of consumer stalls"
    )
