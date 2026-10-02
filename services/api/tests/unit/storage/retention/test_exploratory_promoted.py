"""Cases promoted from E07-Q02 exploratory sessions (docs/qa/exploratory/)."""

from __future__ import annotations

import pytest
from test_reaper import DAY, NOW_US, Env, part

from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.router import dedup_merge


async def test_pin_applied_between_drops_skips_remaining_partitions() -> None:
    env = Env([part("A", 40), part("A", 41), part("B", 40)])
    reaper = env.reaper()
    report = await reaper.dry_run()
    original = env.drop

    async def drop_then_pin(p):  # type: ignore[no-untyped-def]  # test shim
        await original(p)
        env.pinned.add("A")

    env.drop = drop_then_pin  # type: ignore[method-assign]
    await reaper.apply(report)
    drops = [e for e in env.log if e.startswith("drop")]
    assert sum(":A:" in d for d in drops) == 1 and sum(":B:" in d for d in drops) == 1


def test_dedup_epoch_id_distinguishes_snapshots() -> None:
    key = ("ts", "symbol", "depth", "epoch_id")
    a = [{"ts": 1, "symbol": "A", "depth": 50, "epoch_id": 1}]
    b = [{"ts": 1, "symbol": "A", "depth": 50, "epoch_id": 2}]
    assert len(dedup_merge(a, b, key)) == 2


def test_dedup_same_key_altered_field_last_writer_wins() -> None:
    key = ("ts", "symbol", "trade_id")
    cold = [{"ts": 1, "symbol": "A", "trade_id": "1", "price": 1}]
    hot = [{"ts": 1, "symbol": "A", "trade_id": "1", "price": 2}]
    assert dedup_merge(cold, hot, key)[0]["price"] == 2


@pytest.mark.xfail(reason="BUG-C: apply() has no single-run guard", strict=True)
async def test_apply_twice_same_report_writes_single_purge_audit() -> None:
    env = Env([part("A", 40)])
    report = await env.reaper().dry_run()
    await env.reaper().apply(report)
    await env.reaper().apply(report)
    assert [a for a, _ in env.audits].count("retention.purge") == 1


async def test_replay_session_created_between_dry_run_and_apply_blocks_drop() -> None:
    p = part("A", 800, "cold")
    env = Env([p])
    reaper = env.reaper()
    report = await reaper.dry_run()
    assert [i.action for i in report.to_drop] == ["drop"]
    env.replay[p] = "sess-late"
    result = await reaper.apply(report)
    assert not any(e.startswith("drop") for e in env.log)
    assert any(i.detail == "session_id=sess-late" for i in result.skipped)


@pytest.mark.xfail(reason="BUG-A: router boundary ignores accelerated window", strict=True)
async def test_router_resolves_cold_when_reaper_accelerated_window_shrinks() -> None:
    """Free disk 8% halves the hot window to 15d (reaper); router must follow."""
    from candleviewer.storage.router import TierRouter

    env = Env([part("A", 20)], free=8.0)
    reaper = env.reaper()
    report = await reaper.dry_run()
    assert report.accelerated and len(report.to_drop) == 1  # 20d-old hot dropped
    router = TierRouter({}, {}, lambda s: 30, clock_us=lambda: NOW_US)
    rng = TimeRange(start_us=NOW_US - 21 * DAY, end_us=NOW_US - 20 * DAY)
    assert router.resolve(StreamKind.TRADES, rng) != "hot"


@pytest.mark.xfail(reason="BUG-A (class): no monotonic-clock guard in router", strict=True)
def test_router_clock_step_back_does_not_lose_rows() -> None:
    from candleviewer.storage.router import TierRouter

    t = [NOW_US]
    router = TierRouter({}, {}, lambda s: 30, clock_us=lambda: t[0])
    rng = TimeRange(start_us=NOW_US - 31 * DAY, end_us=NOW_US - 29 * DAY)
    before = router.resolve(StreamKind.TRADES, rng)
    t[0] -= 3 * DAY
    assert router.resolve(StreamKind.TRADES, rng) == before


@pytest.mark.xfail(reason="BUG-B: no signal on dedup collision with differing payload", strict=True)
def test_dedup_collision_with_differing_fields_is_observable(caplog) -> None:  # type: ignore[no-untyped-def]
    key = ("ts", "symbol", "trade_id")
    cold = [{"ts": 1, "symbol": "A", "trade_id": "1", "price": 1}]
    hot = [{"ts": 1, "symbol": "A", "trade_id": "1", "price": 2}]
    dedup_merge(cold, hot, key)
    assert caplog.records
