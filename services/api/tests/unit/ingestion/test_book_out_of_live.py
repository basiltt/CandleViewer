"""#1919: `BookStream.out_of_live` bookkeeping (resync SLO = backoff cap)."""

from __future__ import annotations

from candleviewer.orderbook_wiring import RESYNC_BACKOFF_CAP_S, BookStream


def _bare(clock: list[float]) -> BookStream:
    s = object.__new__(BookStream)
    s._clock = lambda: clock[0]
    s._not_live_since = {}
    return s


def test_out_of_live_flags_only_past_slo() -> None:
    clock = [100.0]
    s = _bare(clock)
    s._not_live_since["BTCUSDT"] = 100.0
    clock[0] = 100.0 + RESYNC_BACKOFF_CAP_S
    assert s.out_of_live() == ()
    clock[0] += 0.001
    assert s.out_of_live() == ("BTCUSDT",)
    s._not_live_since.pop("BTCUSDT")
    assert s.out_of_live() == ()
