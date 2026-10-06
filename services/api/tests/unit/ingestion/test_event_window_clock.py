"""#1912: the #1892 EventWindow runs on the exchange-corrected clock (E08-S07)."""

from __future__ import annotations

import asyncio

import pytest

from candleviewer.exchange.base.frame_guard import MAX_FUTURE_SKEW_MS, FrameRejectedError
from candleviewer.ingestion.clock import ClockGuard
from candleviewer.ingestion.metrics import clock_resync_triggered_total
from candleviewer.ingestion.rejection import EventWindow, corrected_now_us

_S = 1_000_000
_VENUE_US = 1_800_000_000 * _S


class _Host:
    def __init__(self, now_us: int) -> None:
        self.now_us = now_us

    def __call__(self) -> int:
        return self.now_us


class _Clocks:
    """Fake wall + monotonic clocks; `step` moves only the wall clock (host step)."""

    def __init__(self) -> None:
        self.mono_ns = 5_000 * 1_000_000_000
        self.wall_base_ns = _VENUE_US * 1000 - self.mono_ns  # host == venue at t0

    def wall(self) -> int:
        return self.mono_ns + self.wall_base_ns

    def mono(self) -> int:
        return self.mono_ns

    def host_us(self) -> int:
        return self.wall() // 1000

    def step(self, seconds: float) -> None:
        self.wall_base_ns += int(seconds * 1_000_000_000)

    def advance(self, seconds: float) -> None:
        self.mono_ns += int(seconds * 1_000_000_000)


def _guard(clocks: _Clocks, fetches: list[int] | None = None) -> ClockGuard:
    async def _fetch() -> tuple[int, float, float]:
        if fetches is not None:
            fetches.append(1)
        # venue time is the true time: unaffected by host steps
        return (_VENUE_US + clocks.mono_ns // 1000 - 5_000 * _S, clocks.wall() / 1e9, 0.0)

    return ClockGuard(
        _fetch, sample_count=1, wall_ns=clocks.wall, mono_ns=clocks.mono, step_check_interval_ms=0
    )


def _window(clocks: _Clocks, guard: ClockGuard) -> EventWindow:
    return EventWindow(corrected_now_us(guard.offset_us, clocks.host_us), lambda _s: None)


def _venue_now(clocks: _Clocks) -> int:
    return _VENUE_US + clocks.mono_ns // 1000 - 5_000 * _S


def _steps() -> float:
    return float(clock_resync_triggered_total.labels(reason="host_step")._value.get())


def test_corrected_now_positive_offset_when_venue_ahead_of_host() -> None:
    host = _Host(_VENUE_US - 10 * _S)  # host 10 s behind venue
    assert corrected_now_us(lambda: 10 * _S, host)() == _VENUE_US  # server - local > 0


def test_backward_host_step_without_remeasure_accepts_venue_prints() -> None:
    clocks = _Clocks()
    guard = _guard(clocks)
    window = _window(clocks, guard)
    window("BTCUSDT", _venue_now(clocks))
    clocks.step(-10)  # WSL resume; no re-measure has happened
    window("BTCUSDT", _venue_now(clocks))  # no ts_future
    assert guard.offset_us() == 10 * _S


def test_backward_host_step_uncorrected_window_rejects() -> None:
    clocks = _Clocks()
    clocks.step(-10)
    window = EventWindow(clocks.host_us, lambda _s: None)
    with pytest.raises(FrameRejectedError) as ei:
        window("BTCUSDT", _venue_now(clocks))
    assert ei.value.reason == "ts_future"


def test_forward_host_step_symmetric() -> None:
    clocks = _Clocks()
    guard = _guard(clocks)
    window = _window(clocks, guard)
    clocks.step(10)
    window("BTCUSDT", _venue_now(clocks))
    assert guard.offset_us() == -10 * _S


def test_implausible_venue_ts_still_rejected_after_step() -> None:
    clocks = _Clocks()
    guard = _guard(clocks)
    window = _window(clocks, guard)
    clocks.step(-10)
    with pytest.raises(FrameRejectedError) as ei:
        window("BTCUSDT", _venue_now(clocks) + MAX_FUTURE_SKEW_MS * 1000 + 1)
    assert ei.value.reason == "ts_future"


def test_step_below_threshold_does_not_trigger() -> None:
    clocks = _Clocks()
    guard = _guard(clocks)
    before = _steps()
    clocks.advance(30)  # elapsed time is not a step
    clocks.step(-0.5)
    assert guard.offset_us() == 0
    assert _steps() == before


async def test_step_triggers_exactly_one_single_flight_measure() -> None:
    clocks = _Clocks()
    fetches: list[int] = []
    guard = _guard(clocks, fetches)
    before = _steps()
    clocks.step(-10)
    guard.offset_us()
    guard.offset_us()  # re-entry while the measure is in flight
    for _ in range(5):
        await asyncio.sleep(0)
    assert len(fetches) == 1
    assert _steps() == before + 1
    assert guard.offset_us() == 10 * _S  # measurement confirms the step correction
    assert len(fetches) == 1  # reference re-based: no re-trigger


def test_offset_tracks_guard_without_double_apply() -> None:
    clocks = _Clocks()
    guard = _guard(clocks)
    now = corrected_now_us(guard.offset_us, clocks.host_us)
    assert now() == clocks.host_us()  # unmeasured offset is 0
    guard._offset_us = 7 * _S
    assert now() == clocks.host_us() + 7 * _S
