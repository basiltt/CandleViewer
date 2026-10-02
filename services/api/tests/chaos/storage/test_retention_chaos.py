"""Chaos scenarios 3, 8, 9 (E07-Q04): disk-full guard, reaper race, clock step.

Controls verified: SR-096 (disk guard, alert before deletion), SR-099
(pins honoured, no double deletion/audit). Docker/loopback-dependent parts
live in `test_docker_scenarios.py`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from candleviewer.storage.cold import exporter as exporter_mod
from candleviewer.storage.models import StreamKind
from candleviewer.storage.retention.policy import RetentionPolicy, load_defaults
from candleviewer.storage.retention.reaper import Reaper
from tests.chaos.storage._harness import Rig
from tests.unit.storage.cold._helpers import day_range
from tests.unit.storage.retention.test_reaper import NOW, Env, part

pytestmark = pytest.mark.chaos


def _reaper(env: Env) -> Reaper:
    return Reaper(
        RetentionPolicy([], load_defaults()), env, env, env, env, env, env, clock=lambda: NOW
    )


async def test_s3_disk_full_alerts_before_any_deletion_and_spares_pinned() -> None:
    env = Env([part("PIN", 40), part("AUTO", 40)], free=3.0)
    env.pinned, env.auto = {"PIN"}, {"PIN", "AUTO"}
    await _reaper(env).run()
    first_event = next(i for i, e in enumerate(env.log) if e == "event:CRITICAL")
    drops = [i for i, e in enumerate(env.log) if e.startswith("drop")]
    assert drops, "accelerated retention should reclaim the non-pinned partition"
    assert first_event < min(drops), "INVARIANT: critical alert precedes every deletion"
    assert env.paused == ["AUTO"], "INVARIANT: only non-pinned auto-recorded symbols paused"
    assert not any(e.startswith("drop:PIN") for e in env.log), "INVARIANT: pinned data untouched"


async def test_s8_two_reapers_racing_do_not_double_delete_or_double_audit() -> None:
    env = Env([part("A", 40)])
    dropped: set[str] = set()
    orig_drop = env.drop

    async def drop_once(p):  # type: ignore[no-untyped-def]
        key = f"{p.symbol}:{p.range.end_us}"
        assert key not in dropped, "INVARIANT: partition deleted twice"
        dropped.add(key)
        await asyncio.sleep(0)
        await orig_drop(p)

    env.drop = drop_once  # type: ignore[method-assign]
    await asyncio.gather(_reaper(env).run(), _reaper(env).run())
    purges = [a for a in env.audits if a[0] == "retention.purge"]
    assert len(purges) == 1, "INVARIANT: exactly one purge audit entry"


async def test_s9_clock_step_backwards_does_not_reexport(rig: Rig) -> None:
    first = await rig.exporter().export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    reads_after_first = rig.source.reads
    stepped_back = datetime(2026, 10, 10, tzinfo=UTC) - timedelta(days=1)
    from candleviewer.storage.cold.exporter import ColdExporter

    ex = ColdExporter(rig.registry, rig.source, clock=lambda: stepped_back, events=rig.sink)
    second = await ex.export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    assert second.run_id == first.run_id, "INVARIANT: window keyed by range, not wall clock"
    assert rig.source.reads == reads_after_first, "INVARIANT: no re-export after clock step"
    assert len(rig.entries()) == 1
    assert exporter_mod._TEST_HOOKS == {}
