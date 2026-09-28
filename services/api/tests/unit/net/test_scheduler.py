"""MeshSelfCheckScheduler (E09-T04 AC5, "drift after resume is caught").

Covers: `run_once()` drives the gate exactly like the boot check does,
`start()`/`stop()` supervise a background loop that is cancellation-safe,
and a timed-out check fails closed (trips read-only) rather than hanging.
"""

from __future__ import annotations

import asyncio

from candleviewer.net.binding_check import BindingSelfCheck
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.net.scheduler import MeshSelfCheckScheduler


class _FakeGauge:
    def __init__(self) -> None:
        self.value: float | None = None

    def set(self, value: float) -> None:
        self.value = value


async def test_run_once_trips_the_gate_on_a_public_binding() -> None:
    check = BindingSelfCheck(address_enumerator=lambda: ["0.0.0.0:8000"])
    gate = ReadOnlyGate()
    gauge = _FakeGauge()
    scheduler = MeshSelfCheckScheduler(check=check, read_only_gate=gate, gauge=gauge)

    await scheduler.run_once()

    assert gate.is_read_only is True
    assert gauge.value == 0


async def test_run_once_clears_a_previously_tripped_gate_on_a_safe_binding() -> None:
    check = BindingSelfCheck(address_enumerator=lambda: ["127.0.0.1:8000"])
    gate = ReadOnlyGate()
    gate.trip(reason_code="net.public_binding_detected", reason_text="stale")
    scheduler = MeshSelfCheckScheduler(check=check, read_only_gate=gate)

    await scheduler.run_once()

    assert gate.is_read_only is False


async def test_run_once_fails_closed_when_the_check_times_out() -> None:
    def _slow() -> list[str]:
        import time

        time.sleep(0.2)
        return ["127.0.0.1:8000"]

    check = BindingSelfCheck(address_enumerator=_slow)
    gate = ReadOnlyGate()
    gauge = _FakeGauge()
    scheduler = MeshSelfCheckScheduler(check=check, read_only_gate=gate, gauge=gauge)

    import candleviewer.net.scheduler as scheduler_mod

    original_timeout = scheduler_mod._SELF_CHECK_TIMEOUT_S
    scheduler_mod._SELF_CHECK_TIMEOUT_S = 0.01
    try:
        await scheduler.run_once()
    finally:
        scheduler_mod._SELF_CHECK_TIMEOUT_S = original_timeout

    assert gate.is_read_only is True
    assert gate.reason_code == "net.self_check_timed_out"
    assert gauge.value == 0


async def test_start_runs_the_loop_and_stop_cancels_it_cleanly() -> None:
    calls = 0

    async def _fake_run_once() -> None:
        nonlocal calls
        calls += 1

    check = BindingSelfCheck(address_enumerator=lambda: ["127.0.0.1:8000"])
    gate = ReadOnlyGate()
    scheduler = MeshSelfCheckScheduler(check=check, read_only_gate=gate, interval_s=0.01)
    scheduler.run_once = _fake_run_once  # type: ignore[method-assign]

    scheduler.start()
    scheduler.start()  # idempotent: must not spawn a second task
    await asyncio.sleep(0.05)
    await scheduler.stop()

    assert calls >= 1
    assert scheduler._task is None


async def test_stop_before_start_is_a_noop() -> None:
    check = BindingSelfCheck(address_enumerator=lambda: ["127.0.0.1:8000"])
    gate = ReadOnlyGate()
    scheduler = MeshSelfCheckScheduler(check=check, read_only_gate=gate)

    await scheduler.stop()  # must not raise

    assert scheduler._task is None
