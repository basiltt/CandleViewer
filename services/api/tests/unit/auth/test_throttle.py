"""Unit tests for `candleviewer.auth.throttle.PerIpLoginThrottle` (E09-S01)."""

from __future__ import annotations

from candleviewer.auth.throttle import PerIpLoginThrottle


def _clock_factory(start: float = 0.0) -> tuple[list[float], object]:
    box = [start]

    def clock() -> float:
        return box[0]

    return box, clock


def test_throttle_not_blocked_below_threshold() -> None:
    box, clock = _clock_factory()
    throttle = PerIpLoginThrottle(max_attempts=3, window_s=60.0, clock=clock)  # type: ignore[arg-type]
    throttle.record_failure("1.2.3.4")
    throttle.record_failure("1.2.3.4")
    assert throttle.is_blocked("1.2.3.4") is False


def test_throttle_blocked_at_threshold() -> None:
    box, clock = _clock_factory()
    throttle = PerIpLoginThrottle(max_attempts=3, window_s=60.0, clock=clock)  # type: ignore[arg-type]
    for _ in range(3):
        throttle.record_failure("1.2.3.4")
    assert throttle.is_blocked("1.2.3.4") is True


def test_throttle_window_expiry_unblocks() -> None:
    box, clock = _clock_factory()
    throttle = PerIpLoginThrottle(max_attempts=2, window_s=10.0, clock=clock)  # type: ignore[arg-type]
    throttle.record_failure("1.2.3.4")
    throttle.record_failure("1.2.3.4")
    assert throttle.is_blocked("1.2.3.4") is True
    box[0] += 11.0
    assert throttle.is_blocked("1.2.3.4") is False


def test_throttle_is_per_source_ip() -> None:
    box, clock = _clock_factory()
    throttle = PerIpLoginThrottle(max_attempts=1, window_s=60.0, clock=clock)  # type: ignore[arg-type]
    throttle.record_failure("1.2.3.4")
    assert throttle.is_blocked("1.2.3.4") is True
    assert throttle.is_blocked("5.6.7.8") is False
