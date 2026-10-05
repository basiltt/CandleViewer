"""E40-T03 review round 2: `once_per_bar` restart uses event time; disarm vs. firing races."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from candleviewer.alerts.evaluator import AlertTick
from candleviewer.alerts.gating import TIMEFRAME_MS, bar_open_ms
from tests.alerts._evaluator_env import T0, ir, make, row

_BAR = bar_open_ms(T0, "5m")
_LATE_IN_BAR = _BAR + TIMEFRAME_MS["5m"] - 1_000


def _bar_tick(ts: int) -> AlertTick:
    return AlertTick("on_bar_close", ts, "BTCUSDT")


def _price_tick() -> AlertTick:
    return AlertTick("on_price_update", T0, "BTCUSDT")


async def test_once_per_bar_restart_event_time_lagging_wall_clock_does_not_refire() -> None:
    r = row("a1", trigger_mode="once_per_bar",
            condition_ir=ir(trigger="on_bar_close", timeframe="5m"))  # fmt: skip
    ev, store, src, clock, _ = make(r)
    await ev.warm_up()
    clock.now = _BAR + TIMEFRAME_MS["5m"] + 5_000  # wall clock already in bar N+1
    src.set("price", 65500, clock.now)  # fresh value; only the tick lags
    await ev.process(_bar_tick(_LATE_IN_BAR))  # exchange event time still in bar N
    [d] = store.deliveries
    assert d.context["bar_open_ms"] == _BAR
    # Restart: a fresh evaluator rebuilt only from the persisted row.
    ev2, store2, src2, clock2, _ = make(store.rows["a1"])
    await ev2.warm_up()
    clock2.now = clock.now + 100
    src2.set("price", 65500, clock2.now)
    await ev2.process(_bar_tick(_LATE_IN_BAR + 500))  # same bar N
    assert store2.deliveries == []


async def test_disarm_after_once_firing_is_a_noop() -> None:
    ev, store, src, _, m = make(row("a1", trigger_mode="once"))
    await ev.warm_up()
    src.set("price", 65500, T0)
    await ev.process(_price_tick())
    await ev.disarm("a1", "price")
    assert [d.context.get("disarmed") for d in store.deliveries] == [None]
    assert m.get("cv_alert_autodisarmed_total", "source_unavailable") == 0


async def test_firing_after_disarm_never_fires() -> None:
    ev, store, src, *_ = make(row("a1", trigger_mode="once"))
    await ev.warm_up()
    await ev.disarm("a1", "price")
    src.set("price", 65500, T0)
    await ev.process(_price_tick())
    assert [d.context.get("disarmed") for d in store.deliveries] == [True]
    assert store.rows["a1"].enabled is False


async def test_concurrent_disarm_and_firing_commit_exactly_one_outcome() -> None:
    for disarm_first in (True, False):
        ev, store, src, *_ = make(row("a1", trigger_mode="once"))
        await ev.warm_up()
        src.set("price", 65500, T0)
        fire, disarm = ev.process(_price_tick()), ev.disarm("a1", "price")
        await asyncio.gather(*((disarm, fire) if disarm_first else (fire, disarm)))
        assert len(store.deliveries) == 1, disarm_first
        assert store.rows["a1"].enabled is False and "a1" not in ev.alerts


async def test_disarm_when_store_already_disarmed_announces_nothing() -> None:
    ev, store, *_ = make(row("a1"))
    await ev.warm_up()
    store.rows["a1"] = replace(store.rows["a1"], enabled=False)  # another worker disarmed
    await ev.disarm("a1", "price")
    assert store.deliveries == [] and "a1" not in ev.alerts
