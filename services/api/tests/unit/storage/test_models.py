"""Unit tests for `candleviewer.storage.models` (E07-T01)."""

from __future__ import annotations

from datetime import UTC

import pytest
from pydantic import ValidationError

from candleviewer.storage.models import (
    ExportRun,
    RetentionDecision,
    StreamKind,
    SymbolStream,
    TimeRange,
)


def test_timerange_accepts_equal_start_and_end() -> None:
    rng = TimeRange(start_us=100, end_us=100)
    assert rng.start_us == rng.end_us == 100


def test_timerange_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError):
        TimeRange(start_us=200, end_us=100)


def test_timerange_is_frozen() -> None:
    rng = TimeRange(start_us=0, end_us=1)
    with pytest.raises(ValidationError):
        rng.start_us = 5  # type: ignore[misc]


def test_timerange_from_datetimes_round_trips_to_microseconds() -> None:
    from datetime import datetime

    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
    rng = TimeRange.from_datetimes(start, end)
    assert rng.end_us - rng.start_us == 1_000_000


def test_symbol_stream_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        SymbolStream(symbol="BTCUSDT", stream=StreamKind.TRADES, extra="nope")  # type: ignore[call-arg]


def test_stream_kind_has_all_thirteen_streams() -> None:
    expected = {
        "trades",
        "orderbook_delta",
        "orderbook_snapshot",
        "tickers",
        "klines",
        "liquidations",
        "open_interest",
        "funding_rates",
        "bars",
        "footprint_cells",
        "profiles",
        "orderflow_metrics",
        "heatmap_cells",
    }
    assert {s.value for s in StreamKind} == expected


def test_export_run_defaults_unverified() -> None:
    run = ExportRun(
        run_id="r1",
        symbol="BTCUSDT",
        stream=StreamKind.TRADES,
        partition_range=TimeRange(start_us=0, end_us=1),
        row_count=10,
    )
    assert run.verified is False


def test_retention_decision_skip_with_reason() -> None:
    decision = RetentionDecision(
        symbol="BTCUSDT",
        stream=StreamKind.BARS,
        action="skip",
        range=TimeRange(start_us=0, end_us=1),
        reason="pinned",
    )
    assert decision.action == "skip"
    assert decision.reason == "pinned"
