"""Cases promoted from E07-Q02 exploratory sessions (docs/qa/exploratory/)."""

from __future__ import annotations

import pytest
from test_reaper import Env, part

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
