"""E12-T05 (#398): shared `KlineResponse` assembly — cursor codec, meta, null-not-zero, ceiling."""

from __future__ import annotations

from dataclasses import dataclass

import orjson
import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.api import market_response as mr
from candleviewer.bars import limits


@dataclass(frozen=True, slots=True)
class _Row:
    ts_us: int = 0
    open: str = "1"
    high: str = "1"
    low: str = "1"
    close: str = "1"
    volume: str = "1"
    turnover: str = "1"
    confirmed: bool = True


@given(st.integers(min_value=0, max_value=2**63 - 1))
def test_cursor_round_trips_any_ts(ts: int) -> None:
    c = mr.encode_cursor(ts)
    assert len(c) <= 128 and mr.decode_cursor(c) == ts


@pytest.mark.parametrize("bad", ["", "a" * 129, "é", "!!!", "Zm9v", "djE6LTE", "djE6"])
def test_decode_cursor_rejects_foreign_input(bad: str) -> None:
    with pytest.raises(mr.InvalidCursor):
        mr.decode_cursor(bad)


def test_kline_row_with_include_delta_gets_nulls_never_zero() -> None:
    bar = mr.serialize_bar(_Row(), include_delta=True)
    assert all(bar[k] is None for k in ("delta", "min_delta", "max_delta", "cvd"))
    assert "trades" not in bar and "close_time" not in bar


def test_meta_has_more_tracks_cursor_and_omits_holes_when_none() -> None:
    meta = mr.build_meta(count=0, next_cursor=None, sources=[], recording_started_at_us=None,
                         generated_at_us=0)  # fmt: skip
    assert meta["has_more"] is False and "coverage_holes" not in meta
    assert meta["recording_started_at"] is None
    more = mr.build_meta(count=1, next_cursor="x", sources=["tape"], recording_started_at_us=0,
                         generated_at_us=0)  # fmt: skip
    assert more["has_more"] is True and more["recording_started_at"].startswith("1970")


def test_oversized_page_is_response_too_large_not_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mr, "RESPONSE_MAX_BYTES", 200)
    meta = mr.build_meta(count=5, next_cursor=None, sources=[], recording_started_at_us=None,
                         generated_at_us=0)  # fmt: skip
    bars = [mr.serialize_bar(_Row(ts_us=i), include_delta=False) for i in range(5)]
    resp = mr.kline_response(symbol="BTCUSDT", interval="1", bar_type="time", bars=bars, meta=meta)
    assert resp.status_code == 422
    assert orjson.loads(resp.body)["code"] == "response_too_large"


def test_limits_are_the_threat_model_numbers() -> None:
    """SR-E12-01/02/03: a change here is a reviewed threat-model amendment."""
    assert (limits.MAX_LIMIT, limits.DEFAULT_LIMIT) == (5_000, 1_000)
    assert limits.RESPONSE_MAX_BYTES == 2 * 1024 * 1024 and limits.QUERY_TIMEOUT_S == 2.0
    assert limits.MAX_TIME_WINDOW_US == 400 * 86_400_000_000
    assert limits.MAX_NON_TIME_WINDOW_US == 31 * 86_400_000_000
    assert limits.MAX_WINDOW_BARS == 250_000
    assert limits.TICK_PARAM_RANGE == (100, 1_000_000)
    assert limits.RANGE_TICKS_RANGE == (2, 100_000) and limits.QTY_PARAM_MAX == 10**12
