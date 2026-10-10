"""PR #2186 adversarial review: cap preemption/queueing, error retry, warm-up gate."""

from __future__ import annotations

from typing import Any

from candleviewer.recorder.metrics import (
    recorder_b11_error_total,
    recorder_cap_preempted_total,
    recorder_cap_refused_total,
)
from candleviewer.recorder.models import RecorderCapRefused
from candleviewer.recorder.policy import PolicyConfig, RecordingPolicy, user_actor
from tests.unit.recorder.conftest import FakeAudit, FakeBus, FakeClock

OWNER = user_actor("owner-1")


def _cap1(clock: FakeClock, bus: FakeBus, audit: FakeAudit) -> RecordingPolicy:
    p = RecordingPolicy(
        bus=bus, audit=audit, env="demo", now=clock, config=PolicyConfig(max_symbols=1)
    )
    p.positions_reloaded()
    return p


def _value(metric: Any, **labels: str) -> float:
    child = metric.labels(**labels) if labels else metric
    return float(child._value.get())


async def test_position_preempts_chart_only_entry_at_cap(
    clock: FakeClock, bus: FakeBus, audit: FakeAudit
) -> None:
    p = _cap1(clock, bus, audit)
    before = _value(recorder_cap_preempted_total)
    try:
        await p.on_chart_opened("SOLUSDT", "c1")
        clock.advance(60)
        await p.tick()
        await p.on_position_opened("XRPUSDT", "p1")
        assert set(p.effective_set()) == {"XRPUSDT"}
        stops = [kw for a, kw in audit.records if a == "recorder.stop"]
        assert stops[-1]["object_id"] == "SOLUSDT" and stops[-1]["reason"] == "cap_preempted"
        assert _value(recorder_cap_preempted_total) == before + 1
    finally:
        await p.stop()


async def test_position_refused_by_manual_cap_is_warned_then_starts(
    clock: FakeClock, bus: FakeBus, audit: FakeAudit
) -> None:
    """Reviewer probe: max_symbols=1, manual BTC, position XRP."""
    p = _cap1(clock, bus, audit)
    before = _value(recorder_cap_refused_total, reason="position_open")
    try:
        await p.add_manual("BTCUSDT", OWNER)
        await p.on_position_opened("XRPUSDT", "p")
        assert "XRPUSDT" not in p.effective_set()
        warned = [e for _t, e in bus.events if isinstance(e, RecorderCapRefused)]
        assert [(e.symbol, e.reason) for e in warned] == [("XRPUSDT", "position_open")]
        assert _value(recorder_cap_refused_total, reason="position_open") == before + 1
        denied = [kw for a, kw in audit.records if kw.get("outcome") == "denied"]
        assert denied[0]["object_id"] == "XRPUSDT"
        await p.tick()  # still refused: warned once, not per tick
        assert len([e for _t, e in bus.events if isinstance(e, RecorderCapRefused)]) == 1
        await p.remove_manual("BTCUSDT", OWNER)
        clock.advance(1_801)
        await p.tick()
        await p.tick()
        assert p.effective_set()["XRPUSDT"].reason == "position_open"
    finally:
        await p.stop()


async def test_audit_outage_recovers_via_retry(
    policy: RecordingPolicy, audit: FakeAudit, clock: FakeClock
) -> None:
    before = _value(recorder_b11_error_total, env="demo")
    real_emit, failures = audit.emit, [1]

    async def flaky(action: str, **kw: Any) -> None:
        if failures:
            failures.pop()
            raise RuntimeError("audit unavailable")
        await real_emit(action, **kw)

    audit.emit = flaky  # type: ignore[method-assign]  # inject one failing write
    await policy.on_position_opened("XRPUSDT", "p1")
    assert policy.leaf("XRPUSDT") == "error"
    assert _value(recorder_b11_error_total, env="demo") == before + 1
    for _ in range(3):
        await policy.tick()
        clock.advance(1)
    assert policy.leaf("XRPUSDT") == "recording"
    assert audit.actions() == ["recorder.start"]
    await policy.on_position_opened("XRPUSDT", "p2")
    assert policy.effective_set()["XRPUSDT"].reason == "position_open"


async def test_warmup_gate_blocks_stop_until_positions_reloaded(
    clock: FakeClock, bus: FakeBus, audit: FakeAudit
) -> None:
    p = RecordingPolicy(bus=bus, audit=audit, env="demo", now=clock)
    try:
        await p.on_position_opened("ETHUSDT", "p1")
        await p.on_position_closed("ETHUSDT", "p1")
        clock.advance(10_000)
        await p.tick()
        assert p.leaf("ETHUSDT") == "lingering"  # gate closed: no stop decision
        p.positions_reloaded()
        await p.tick()
        assert p.effective_set() == {} and audit.actions()[-1] == "recorder.stop"
    finally:
        await p.stop()
