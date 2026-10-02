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
from candleviewer.storage.retention.reaper import (
    Reaper,
    storage_disk_free_ratio,
    storage_retention_runs_total,
)
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


class _Shared(Env):
    """One backing store seen by two reaper instances (separate volumes => no in-process lock)."""

    def __init__(self, parts) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parts)
        self.drops: list[str] = []

    async def drop(self, p):  # type: ignore[no-untyped-def]
        assert p in self.parts, "INVARIANT: partition deleted twice"
        self.drops.append(f"{p.symbol}:{p.range.end_us}")
        await super().drop(p)  # removal is atomic, like a real DROP PARTITION
        await asyncio.sleep(0)


def _named(env: Env, volume: str) -> Reaper:
    return Reaper(
        RetentionPolicy([], load_defaults()),
        env, env, env, env, env, env,
        clock=lambda: NOW,
        volume=volume,
    )  # fmt: skip


async def test_s8_cross_instance_race_is_idempotent_no_double_delete_or_audit() -> None:
    env = _Shared([part("A", 40)])
    await asyncio.gather(_named(env, "a").run(), _named(env, "b").run())
    assert len(env.drops) == 1, "INVARIANT: partition deleted exactly once"
    purges = [a for a in env.audits if a[0] == "retention.purge"]
    assert len(purges) == 1, "INVARIANT: exactly one purge audit entry (C-2.9)"
    assert not env.parts


async def test_s8_same_volume_second_run_is_locked_out_and_counted() -> None:
    env = _Shared([part("A", 40)])
    before = storage_retention_runs_total.labels(result="skipped_locked")._value.get()  # type: ignore[attr-defined]
    await asyncio.gather(_named(env, "v").run(), _named(env, "v").run())
    after = storage_retention_runs_total.labels(result="skipped_locked")._value.get()  # type: ignore[attr-defined]
    assert len(env.drops) == 1
    assert len([a for a in env.audits if a[0] == "retention.purge"]) == 1
    assert after - before == 1, "signal: lock-out counted in storage_retention_runs_total"


async def test_s3_disk_critical_emits_event_signal_and_gauge() -> None:
    env = Env([part("AUTO", 40)], free=3.0)
    env.auto = {"AUTO"}
    await _reaper(env).run()
    assert env.events and env.events[0][0] == "CRITICAL", "signal: system_events CRITICAL"
    assert storage_disk_free_ratio.labels(volume="data")._value.get() == pytest.approx(0.03)  # type: ignore[attr-defined]


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
