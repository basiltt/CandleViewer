"""E40-T03 `AlertEvaluator`: the seven Gherkin scenarios plus warm-up / re-keying."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from candleviewer.alerts.evaluator import AlertTick
from candleviewer.alerts.gating import TIMEFRAME_MS, StormSuppressor, bar_open_ms
from tests.alerts._evaluator_env import T0, ir, make, row


def tick(ts: int = T0, sym: str | None = "BTCUSDT", trig: str = "on_price_update") -> AlertTick:
    return AlertTick(trig, ts, sym)


async def test_evaluator_price_cross_no_client_commits_delivery_with_values() -> None:
    ev, store, src, clock, m = make(row("a1", condition_ir=ir("crosses_above")))
    await ev.warm_up()
    src.set("price", 64990, T0)
    await ev.process(tick())
    assert store.deliveries == []
    clock.now = T0 + 100
    src.set("price", 65010, T0 + 100)
    await ev.process(tick(T0 + 100))
    [d] = store.deliveries
    assert d.status == "queued" and store.outbox == [d.id]
    assert d.context["values"] == {"price": "65010"} and d.context["symbol"] == "BTCUSDT"
    assert m.get("cv_alert_fires_total", "every_time") == 1
    assert m.get("cv_alert_eval_latency_seconds") == 1


async def test_evaluator_once_concurrent_double_fire_creates_exactly_one_delivery() -> None:
    ev, store, src, *_ = make(row("a1", trigger_mode="once"))
    await ev.warm_up()
    src.set("price", 65500, T0)
    await asyncio.gather(ev.process(tick()), ev.process(tick()))
    assert len(store.deliveries) == 1
    assert store.rows["a1"].enabled is False and "a1" not in ev.alerts
    assert ev.subscriptions == {}


async def test_evaluator_once_lost_race_in_store_discards_firing() -> None:
    ev, store, src, *_ = make(row("a1", trigger_mode="once"))
    await ev.warm_up()
    store.rows["a1"] = replace(store.rows["a1"], enabled=False)  # another worker won
    src.set("price", 65500, T0)
    await ev.process(tick())
    assert store.deliveries == [] and "a1" not in ev.alerts


async def test_evaluator_every_time_respects_cooldown_and_rearm_visible_on_row() -> None:
    ev, store, src, clock, m = make(row("a1", cooldown_seconds=60))
    await ev.warm_up()
    for s in range(0, 181, 5):  # condition true continuously for 3 minutes
        clock.now = T0 + s * 1000
        src.set("price", 65500, clock.now)
        await ev.process(tick(clock.now))
    assert len(store.deliveries) == 4  # t = 0, 60, 120, 180 s
    assert store.rows["a1"].last_fired_at == datetime.fromtimestamp((T0 + 180_000) / 1000, UTC)
    assert m.get("cv_alert_suppressed_total", "cooldown") > 0


async def test_evaluator_once_per_bar_late_tick_does_not_fire_twice() -> None:
    r = row("a1", trigger_mode="once_per_bar",
            condition_ir=ir(trigger="on_bar_close", timeframe="5m"))  # fmt: skip
    ev, store, src, clock, _ = make(r)
    await ev.warm_up()
    bar = bar_open_ms(T0, "5m")
    src.set("price", 65500, T0)
    await ev.process(tick(bar + 10, trig="on_bar_close"))
    nxt = bar + TIMEFRAME_MS["5m"]
    clock.now = nxt + 5
    src.set("price", 65500, clock.now)
    await ev.process(tick(nxt + 5, trig="on_bar_close"))
    await ev.process(tick(bar + 299_000, trig="on_bar_close"))  # LATE revision of bar 0
    assert [d.context["bar_open_ms"] for d in store.deliveries] == [bar, nxt]


async def test_evaluator_once_per_bar_restart_does_not_reopen_fired_bar() -> None:
    fired = datetime.fromtimestamp(T0 / 1000, UTC)
    r = row("a1", trigger_mode="once_per_bar", last_fired_at=fired,
            last_bar_open_ms=bar_open_ms(T0, "5m"),
            condition_ir=ir(trigger="on_bar_close", timeframe="5m"))  # fmt: skip
    ev, store, src, *_ = make(r)
    await ev.warm_up()  # bar memory rebuilt from the stored bar_open_ms
    src.set("price", 65500, T0)
    await ev.process(tick(T0 + 1, trig="on_bar_close"))
    assert store.deliveries == []


async def test_evaluator_storm_25_firings_aggregate_without_losing_history() -> None:
    rows = [row(f"a{i:02}", symbol=f"S{i % 3}USDT", condition_ir=ir(const=i)) for i in range(25)]
    ev, store, src, clock, m = make(*rows)
    await ev.warm_up()
    src.set("price", 70000, T0)
    await ev.process(tick(sym=None))
    queued = [d for d in store.deliveries if d.status == "queued"]
    suppressed = [d for d in store.deliveries if d.status == "suppressed"]
    assert len(queued) == 20 and len(suppressed) == 5  # all 25 kept in history
    assert all(d.context["suppressed_reason"] == "storm" for d in suppressed)
    assert len(store.outbox) == 20  # suppressed rows are never dispatched
    assert m.get("cv_alert_suppressed_total", "storm") == 5
    clock.now = T0 + 60_000  # window end: one summary delivery
    await ev.flush_storms()
    [summary] = store.deliveries[25:]
    assert summary.status == "queued" and summary.context["suppressed"] == 5
    assert summary.title == "5 further alerts fired for S2USDT and 2 others"
    await ev.flush_storms(force=True)
    assert len(store.deliveries) == 26  # flushed exactly once


async def test_evaluator_storm_summary_single_symbol_title() -> None:
    ev, *_ = make()
    from candleviewer.alerts.evaluator import _Storm

    assert ev.summary_title(_Storm(0, "a", 1, {"BTCUSDT": None})) == (
        "1 further alerts fired for BTCUSDT"
    )
    two = _Storm(0, "a", 3, {"A": None, "B": None})
    assert ev.summary_title(two).endswith("A and 1 other")


async def test_evaluator_suppressed_once_alert_still_disarms() -> None:
    ev, store, src, *_ = make(row("a1", trigger_mode="once"), storm=StormSuppressor(limit=0))
    await ev.warm_up()
    src.set("price", 65500, T0)
    await ev.process(tick())
    assert [d.status for d in store.deliveries] == ["suppressed"]
    assert store.rows["a1"].enabled is False and "a1" not in ev.alerts


async def test_evaluator_dead_source_disarms_loudly_with_reason() -> None:
    ev, store, src, _, m = make(row("a1"), row("a2"))
    await ev.warm_up()
    src.set("price", None, T0, reason="source_unavailable")
    await ev.process(tick())
    assert len(store.deliveries) == 2
    for d in store.deliveries:
        assert d.status == "queued" and "price data source unavailable" in d.title
        assert d.context == {"disarmed": True, "reason": "source_unavailable", "metric": "price"}
    assert not store.rows["a1"].enabled and not store.rows["a2"].enabled
    assert ev.alerts == {} and m.get("cv_alert_autodisarmed_total", "source_unavailable") == 2
    await ev.disarm("gone", "price")  # unknown alert: no-op


async def test_evaluator_stale_or_warmup_value_never_fires_nor_disarms() -> None:
    ev, store, src, *_ = make(row("a1"))
    await ev.warm_up()
    await ev.process(tick())  # warm-up (unpushed) value
    src.set("price", 65500, T0 - 60_000)  # stale
    await ev.process(tick())
    assert store.deliveries == [] and "a1" in ev.alerts


async def test_evaluator_expired_alert_does_not_fire_and_row_is_kept() -> None:
    exp = datetime.fromtimestamp((T0 - 1) / 1000, UTC)
    ev, store, src, _, m = make(row("a1", expires_at=exp))
    await ev.warm_up()
    src.set("price", 65500, T0)
    await ev.process(tick())
    assert store.deliveries == [] and "a1" in store.rows  # Triggered/Expired, not vanished
    assert "a1" not in ev.alerts and m.get("cv_alert_suppressed_total", "expired") == 1
