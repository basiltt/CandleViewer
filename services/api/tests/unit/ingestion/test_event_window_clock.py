"""#1912: the #1892 EventWindow runs on the exchange-corrected clock (E08-S07)."""

from __future__ import annotations

import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.base.frame_guard import MAX_FUTURE_SKEW_MS, FrameRejectedError
from candleviewer.ingestion.clock import ClockGuard
from candleviewer.ingestion.rejection import EventWindow, corrected_now_us

_S = 1_000_000
_VENUE_US = 1_800_000_000 * _S


class _Host:
    def __init__(self, now_us: int) -> None:
        self.now_us = now_us

    def __call__(self) -> int:
        return self.now_us


def _window(host: _Host, offset_us: int | None) -> EventWindow:
    provider = None if offset_us is None else (lambda: offset_us)
    return EventWindow(corrected_now_us(provider, host), lambda _s: None)


def test_corrected_now_positive_offset_when_venue_ahead_of_host() -> None:
    host = _Host(_VENUE_US - 10 * _S)  # host 10 s behind venue
    guard_offset = 10 * _S  # ClockGuard: server - local
    assert corrected_now_us(lambda: guard_offset, host)() == _VENUE_US


def test_backward_host_jump_does_not_reject_live_prints() -> None:
    host = _Host(_VENUE_US - 10 * _S)
    window = _window(host, 10 * _S)
    window("BTCUSDT", _VENUE_US)  # no ts_future


def test_backward_host_jump_without_correction_rejects() -> None:
    window = _window(_Host(_VENUE_US - 10 * _S), None)
    with pytest.raises(FrameRejectedError) as ei:
        window("BTCUSDT", _VENUE_US)
    assert ei.value.reason == "ts_future"


def test_forward_host_jump_symmetric() -> None:
    host = _Host(_VENUE_US + 10 * _S)
    window = _window(host, -10 * _S)
    window("BTCUSDT", _VENUE_US)


def test_implausible_venue_ts_still_rejected_beyond_corrected_now() -> None:
    host = _Host(_VENUE_US - 10 * _S)
    window = _window(host, 10 * _S)
    with pytest.raises(FrameRejectedError) as ei:
        window("BTCUSDT", _VENUE_US + MAX_FUTURE_SKEW_MS * 1000 + 1)
    assert ei.value.reason == "ts_future"


def test_offset_tracks_guard_updates_without_double_apply() -> None:
    async def _fetch() -> tuple[int, float, float]:
        raise AssertionError("not called")

    guard = ClockGuard(_fetch)
    host = _Host(_VENUE_US)
    now = corrected_now_us(guard.offset_us, host)
    assert now() == _VENUE_US  # unmeasured offset is 0
    guard._offset_us = 7 * _S
    assert now() == _VENUE_US + 7 * _S


def test_no_guard_falls_back_to_host_clock_and_logs_once() -> None:
    host = _Host(_VENUE_US)
    with capture_logs() as logs:
        now = corrected_now_us(None, host)
        now()
        now()
    assert now() == _VENUE_US
    assert [e["event"] for e in logs] == ["event_window_host_clock_uncorrected"]
