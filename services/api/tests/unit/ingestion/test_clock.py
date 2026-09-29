"""Unit tests for `ClockGuard` (E08-S07 Test plan: "offset maths incl.
outlier rejection, threshold transitions, single-retry contract")."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from candleviewer.exchange.base.errors import ClockDriftError
from candleviewer.ingestion.clock import (
    ClockGuard,
    ClockMeasurementUnavailableError,
    ServerTimeFetcher,
)


def _fake_clock(start: float = 1_000.0) -> tuple[Callable[[], float], Callable[[float], None]]:
    state = {"t": start}

    def clock() -> float:
        return state["t"]

    def advance(delta: float) -> None:
        state["t"] += delta

    return clock, advance


async def _noop_sleep(_seconds: float) -> None:
    return None


def _fetcher_returning(
    *offsets_us: int, rtts: tuple[float, ...] | None = None
) -> ServerTimeFetcher:
    """Build a `ServerTimeFetcher` returning one `(offset, monotonic, rtt)`
    tuple per call, cycling if exhausted. `monotonic` is fixed at 0 in each
    call for simplicity — only relative offset/rtt matter for these tests."""
    calls = {"i": 0}
    rtt_values = rtts if rtts is not None else tuple(0.01 for _ in offsets_us)

    async def _fetch() -> tuple[int, float, float]:
        i = calls["i"] % len(offsets_us)
        calls["i"] += 1
        offset_us = offsets_us[i]
        rtt_s = rtt_values[i]
        sent_monotonic_s = 0.0
        server_time_us = int((sent_monotonic_s + rtt_s / 2) * 1_000_000) + offset_us
        return server_time_us, sent_monotonic_s, rtt_s

    return _fetch


@pytest.mark.asyncio
async def test_measure_once_computes_round_trip_corrected_offset() -> None:
    clock, _advance = _fake_clock()
    fetcher = _fetcher_returning(50_000, 50_000, 50_000)
    guard = ClockGuard(fetcher, clock=clock, sleep=_noop_sleep, sample_count=3)
    offset_us = await guard.measure_once()
    assert offset_us == 50_000
    assert guard.offset_us() == 50_000


@pytest.mark.asyncio
async def test_measure_once_discards_the_slow_outlier_sample() -> None:
    """One sample has a far-above-average RTT (and a badly wrong offset);
    it must be discarded so the result stays close to the clean samples
    (scenario "Measurement is robust to a slow sample")."""
    clock, _advance = _fake_clock()
    fetcher = _fetcher_returning(
        100_000,
        100_000,
        5_000_000,  # the slow, poisoned sample
        rtts=(0.01, 0.01, 5.0),
    )
    guard = ClockGuard(fetcher, clock=clock, sleep=_noop_sleep, sample_count=3)
    offset_us = await guard.measure_once()
    assert abs(offset_us - 100_000) < 1_000


@pytest.mark.asyncio
async def test_measure_once_all_samples_fail_raises_and_keeps_last_offset() -> None:
    clock, _advance = _fake_clock()
    good_fetcher = _fetcher_returning(10_000)
    guard = ClockGuard(good_fetcher, clock=clock, sleep=_noop_sleep, sample_count=1)
    await guard.measure_once()
    assert guard.offset_us() == 10_000

    async def _failing() -> tuple[int, float, float]:
        raise ConnectionError("network unreachable")

    guard_fail = ClockGuard(_failing, clock=clock, sleep=_noop_sleep, sample_count=2)
    with pytest.raises(ClockMeasurementUnavailableError):
        await guard_fail.measure_once()
    # never measured -> offset stays at the uncorrected default, never a
    # fabricated value.
    assert guard_fail.offset_us() == 0


@pytest.mark.asyncio
async def test_offset_age_advances_and_is_infinite_before_first_measurement() -> None:
    clock, advance = _fake_clock()
    fetcher = _fetcher_returning(1_000)
    guard = ClockGuard(fetcher, clock=clock, sleep=_noop_sleep, sample_count=1)
    assert guard.offset_age_s() == float("inf")
    await guard.measure_once()
    assert guard.offset_age_s() == 0.0
    advance(12.5)
    assert guard.offset_age_s() == pytest.approx(12.5)


@pytest.mark.asyncio
async def test_assert_healthy_raises_before_first_measurement() -> None:
    fetcher = _fetcher_returning(0)
    guard = ClockGuard(fetcher, sleep=_noop_sleep)
    with pytest.raises(ClockDriftError):
        guard.assert_healthy()


@pytest.mark.asyncio
async def test_assert_healthy_passes_within_hard_threshold() -> None:
    fetcher = _fetcher_returning(1_000_000)  # 1000 ms
    guard = ClockGuard(fetcher, sleep=_noop_sleep, hard_threshold_ms=2_000)
    await guard.measure_once()
    guard.assert_healthy()  # must not raise


@pytest.mark.asyncio
async def test_assert_healthy_raises_above_hard_threshold() -> None:
    fetcher = _fetcher_returning(2_500_000)  # 2500 ms
    guard = ClockGuard(fetcher, sleep=_noop_sleep, hard_threshold_ms=2_000)
    await guard.measure_once()
    with pytest.raises(ClockDriftError):
        guard.assert_healthy()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("offset_us", "expected_severity"),
    [
        (0, "ok"),
        (600_000, "warn"),  # 600 ms > 500 ms warn threshold
        (2_500_000, "critical"),  # 2500 ms > 2000 ms hard threshold
    ],
)
async def test_health_severity_matches_drift_thresholds(
    offset_us: int, expected_severity: str
) -> None:
    fetcher = _fetcher_returning(offset_us)
    guard = ClockGuard(fetcher, sleep=_noop_sleep, warn_threshold_ms=500, hard_threshold_ms=2_000)
    await guard.measure_once()
    assert guard.health_severity() == expected_severity


@pytest.mark.asyncio
async def test_describe_reports_direction_and_magnitude_in_seconds() -> None:
    fetcher = _fetcher_returning(1_200_000)  # 1200 ms ahead
    guard = ClockGuard(fetcher, sleep=_noop_sleep)
    await guard.measure_once()
    message = guard.describe()
    assert "1.20 s" in message
    assert "ahead of" in message


@pytest.mark.asyncio
async def test_resync_after_signature_failure_triggers_immediate_measurement() -> None:
    fetcher = _fetcher_returning(42_000)
    guard = ClockGuard(fetcher, sleep=_noop_sleep)
    offset_us = await guard.resync_after_signature_failure(reason="signature_failure")
    assert offset_us == 42_000
    assert guard.offset_us() == 42_000


@pytest.mark.asyncio
async def test_start_measures_once_then_stops_cleanly() -> None:
    fetcher = _fetcher_returning(5_000)
    guard = ClockGuard(fetcher, sleep=_noop_sleep, resync_interval_s=0.01)
    await guard.start()
    try:
        assert guard.offset_us() == 5_000
    finally:
        await guard.stop()


@pytest.mark.asyncio
async def test_periodic_resync_task_survives_a_measurement_failure() -> None:
    """Technical notes: "Measurement runs on a supervised task with jitter;
    failures never cancel the task." A failing fetch during the periodic
    loop must not kill the background task."""
    calls = {"n": 0}

    async def _flaky() -> tuple[int, float, float]:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise ConnectionError("simulated outage")
        return 7_000, 0.0, 0.01

    sleep_calls: list[float] = []

    async def _fast_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        await asyncio.sleep(0)

    guard = ClockGuard(
        _flaky,
        sleep=_fast_sleep,
        resync_interval_s=0.0,
        sample_count=1,
        random_fn=lambda: 0.0,
    )
    await guard.start()
    try:
        for _ in range(200):
            if calls["n"] >= 3:
                break
            await asyncio.sleep(0)
        assert calls["n"] >= 3
    finally:
        await guard.stop()


def test_hard_threshold_must_exceed_warn_threshold() -> None:
    with pytest.raises(ValueError):
        ClockGuard(_fetcher_returning(0), warn_threshold_ms=1_000, hard_threshold_ms=500)


def test_health_severity_and_describe_before_first_measurement() -> None:
    guard = ClockGuard(_fetcher_returning(0), sleep=_noop_sleep)
    assert guard.health_severity() == "critical"
    assert guard.describe() == "Clock offset has not been measured yet."


@pytest.mark.asyncio
async def test_periodic_resync_task_survives_an_unexpected_exception() -> None:
    """The periodic loop's broad `except Exception` guard (technical notes:
    "failures never cancel the task") must catch more than the documented
    `ClockMeasurementUnavailableError`."""
    fetcher = _fetcher_returning(3_000)

    async def _fast_sleep(_seconds: float) -> None:
        await asyncio.sleep(0)

    guard = ClockGuard(
        fetcher,
        sleep=_fast_sleep,
        resync_interval_s=0.0,
        sample_count=1,
        random_fn=lambda: 0.0,
    )
    calls = {"n": 0}
    real_measure_once = guard.measure_once

    async def _flaky_measure_once() -> int:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("unexpected bug")
        return await real_measure_once()

    guard.measure_once = _flaky_measure_once  # type: ignore[method-assign]
    await guard.start()
    try:
        for _ in range(200):
            if calls["n"] >= 3:
                break
            await asyncio.sleep(0)
        assert calls["n"] >= 3
        # the offset from the first successful measurement is retained
        # (the RuntimeError on call 2 did not corrupt it or kill the task).
        assert guard.offset_us() == 3_000
    finally:
        await guard.stop()
