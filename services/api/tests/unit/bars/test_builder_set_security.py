"""PR #2030 security review fixes: no cross-user disclosure in cap errors, cap and
blob-discard metrics, concurrent cap race, cold start visible in health, tmp sweep."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from candleviewer.bars.builder_set import STATE_COLD_STARTED
from candleviewer.bars.errors import SpecCapExceeded
from candleviewer.bars.leases import SpecCaps
from candleviewer.bars.metrics import bars_blob_discarded_total, bars_spec_cap_rejected_total
from candleviewer.bars.models import BarSpec
from candleviewer.bars.service import BarsService
from candleviewer.bus.bus import Bus
from candleviewer.health_wiring import register_bars_probe
from candleviewer.observability.health import HealthStatus
from candleviewer.observability.health_probes import BARS, ComponentState, HealthRegistry

from ._set_harness import H1, M1, T3, TOPIC, V5, make_set, settle
from ._trades import SYM, trade, us


def _count(metric: object, reason: str) -> float:
    return float(metric.labels(reason=reason)._value.get())  # type: ignore[attr-defined]


async def test_cap_error_never_names_another_users_spec(tmp_path: Path) -> None:
    s = make_set(tmp_path, caps=SpecCaps(per_symbol=2, per_user=2))
    await s.register(M1, SYM, "alice-chart", user="alice")
    await s.register(H1, SYM, "alice-chart2", user="alice")
    with pytest.raises(SpecCapExceeded) as ei:
        await s.register(T3, SYM, "bob-chart", user="bob")
    msg = str(ei.value)
    assert ei.value.cap == "per-symbol" and ei.value.own == ()
    assert M1.spec_hash not in msg and H1.spec_hash not in msg
    # the per-user refusal may list the caller's OWN series, and only those
    with pytest.raises(SpecCapExceeded) as own:
        await s.register(V5, "ETHUSDT", "alice-3", user="alice")
    assert own.value.cap == "per-user"
    assert set(own.value.own) == {M1.spec_hash, H1.spec_hash}
    await s.stop()


async def test_cap_rejection_metric_counts_each_refusal(tmp_path: Path) -> None:
    s = make_set(tmp_path, caps=SpecCaps(per_symbol=1))
    before = _count(bars_spec_cap_rejected_total, "per-symbol")
    await s.register(M1, SYM, "a")
    for c in ("b", "c"):
        with pytest.raises(SpecCapExceeded):
            await s.register(H1, SYM, c)
    assert _count(bars_spec_cap_rejected_total, "per-symbol") == before + 2
    await s.stop()


async def test_concurrent_registrations_race_cap_exactly_cap_succeed(tmp_path: Path) -> None:
    cap = 5
    s = make_set(tmp_path, caps=SpecCaps(per_symbol=cap))
    specs = [BarSpec(kind="tick", tick_count=100 + i) for i in range(20)]
    results = await asyncio.gather(
        *(s.register(sp, SYM, f"c{i}") for i, sp in enumerate(specs)), return_exceptions=True
    )
    ok = [r for r in results if r is None]
    refused = [r for r in results if isinstance(r, SpecCapExceeded)]
    assert len(ok) == cap and len(refused) == len(specs) - cap
    assert len(s.active(SYM)) == cap
    await s.stop()


async def test_discarded_blob_counts_metric_and_degrades_health(tmp_path: Path) -> None:
    bus = Bus()
    s1 = make_set(tmp_path, bus=bus)
    await s1.register(T3, SYM, "a")
    await bus.publish(TOPIC, trade(us("10:00:00"), seq=1))
    await settle(bus, s1)
    await s1.stop()
    (tmp_path / SYM / f"{T3.spec_hash}.state.json").write_bytes(b"\x00 truncated")
    before = _count(bars_blob_discarded_total, "corrupt")

    s2 = make_set(tmp_path)
    svc = BarsService()
    svc.attach(s2)
    await svc.start(None)  # type: ignore[arg-type]  # ctx unused by start()
    assert svc.health().status is HealthStatus.OK
    await s2.register(T3, SYM, "a")
    assert _count(bars_blob_discarded_total, "corrupt") == before + 1
    report = svc.health()
    assert report.status is HealthStatus.DEGRADED
    assert report.detail == STATE_COLD_STARTED.value == "bar_state_blob_cold_started"

    registry = HealthRegistry()
    register_bars_probe(registry, svc.health)
    result = await registry._probes[BARS].check()
    assert result.state is ComponentState.DEGRADED and result.detail == STATE_COLD_STARTED.value
    await svc.stop(1.0)
    assert svc.health().status is HealthStatus.STOPPED
    stopped = await registry._probes[BARS].check()
    assert stopped.state is ComponentState.NOT_DEPLOYED


async def test_bars_probe_healthy_without_set() -> None:
    svc = BarsService()
    await svc.start(None)  # type: ignore[arg-type]  # ctx unused by start()
    registry = HealthRegistry()
    register_bars_probe(registry, svc.health)
    assert (await registry._probes[BARS].check()).state is ComponentState.HEALTHY
    await svc.stop(1.0)


async def test_start_sweeps_stale_tmp_blobs(tmp_path: Path) -> None:
    stale = tmp_path / SYM / f"{T3.spec_hash}.state.json.tmp"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"half")
    keep = tmp_path / SYM / f"{T3.spec_hash}.state.json"
    keep.write_bytes(b"{}")
    s = make_set(tmp_path)
    await s.start()
    assert not stale.exists() and keep.exists()
    await s.stop()
    assert await make_set(tmp_path / "absent")._store.sweep_tmp() == 0
