"""E12-T05 (#398): the tape tier adapter (`tape_time_bar_reader`), `StoredBar` mapping and the
endpoint metrics' allow-listed labels."""

from __future__ import annotations

import asyncio

from candleviewer.bars import metrics as bm
from candleviewer.bars.models import BarSpec
from candleviewer.bars.reader import BarReader, stored_bar, tape_time_bar_reader
from candleviewer.bars.rows import bar_param_for, row_checksum
from candleviewer.ingestion.kline_coverage import Range


def _row(ts: int, source: str | None = "tape", **kw: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts": ts, "close_ts": ts + 59_999_999, "symbol": "BTCUSDT",
        "bar_param": bar_param_for(BarSpec(kind="time", interval_ms=60_000)),
        "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 4.0, "buy_volume": 3.0,
        "sell_volume": 1.0, "delta": 2.0, "min_delta": -1.0, "max_delta": 2.5, "delta_pct": 50.0,
        "trade_count": 9, "vwap": 1.25, "is_closed": True, "build_version": 1, "source": source,
        **kw,
    }  # fmt: skip
    row["row_checksum"] = row_checksum(row) if source is not None else None
    return row


class _Fetch:
    def __init__(self, rows: list[dict[str, object]], exc: BaseException | None = None) -> None:
        self.rows, self.exc, self.calls = rows, exc, 0

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.rows


async def _noop(*a: object) -> None: ...


def _read(fetch: _Fetch, interval: str = "1") -> list[object]:
    reader = tape_time_bar_reader(BarReader(fetch, _noop), timeout_s=1.0)
    return list(asyncio.run(reader("BTCUSDT", interval, Range(0, 10**12), 10)))


def test_stored_bar_maps_tape_row_with_order_flow() -> None:
    bar = stored_bar(_row(60_000_000))
    assert (bar.ts_us, bar.close_ts_us, bar.trades) == (60_000_000, 119_999_999, 9)
    assert (bar.delta, bar.min_delta, bar.max_delta) == ("2.0", "-1.0", "2.5")
    assert bar.turnover == "5.0" and bar.confirmed and bar.tape_built


def test_stored_bar_turnover_uses_decimal_product_not_float_product() -> None:
    # float 0.1 * 3.0 == 0.30000000000000004 (1 ULP off); the Decimal product is exactly 0.3.
    assert 0.1 * 3.0 != 0.3
    assert stored_bar(_row(0, vwap=0.1, volume=3.0)).turnover == "0.3"


def test_stored_bar_kline_sourced_row_has_null_delta() -> None:
    bar = stored_bar(_row(0, source="kline"))
    assert (bar.delta, bar.min_delta, bar.max_delta) == (None, None, None)
    assert not bar.tape_built


def test_legacy_null_source_row_is_tape() -> None:
    assert stored_bar(_row(0, source=None)).tape_built


def test_reader_returns_only_tape_built_rows() -> None:
    got = _read(_Fetch([_row(0), _row(60_000_000, source="kline")]))
    assert [b.ts_us for b in got] == [0]  # type: ignore[attr-defined]  # StoredBar


def test_reader_degrades_to_empty_on_storage_failure() -> None:
    fetch = _Fetch([], exc=ConnectionError("down"))
    assert _read(fetch) == [] and fetch.calls == 1


def test_reader_month_interval_and_empty_window_do_not_query() -> None:
    fetch = _Fetch([_row(0)])
    assert _read(fetch, "M") == [] and fetch.calls == 0
    reader = tape_time_bar_reader(BarReader(fetch, _noop), timeout_s=1.0)
    assert asyncio.run(reader("BTCUSDT", "1", Range(5, 5), None)) == [] and fetch.calls == 0


def test_record_page_only_counts_allow_listed_labels() -> None:
    from prometheus_client import REGISTRY

    def v(name: str, labels: dict[str, str]) -> float:
        return float(REGISTRY.get_sample_value(name, labels) or 0.0)

    before = v("bars_endpoint_source_tier_total", {"endpoint_group": "klines", "stream": "tape"})
    rows_before = v("bars_endpoint_rows_returned_total", {"endpoint_group": "klines"})
    bm.record_page("klines", 3, ["tape", "evil-tier"])
    bm.record_page("nope", 3, ["tape"])
    assert (
        v("bars_endpoint_source_tier_total", {"endpoint_group": "klines", "stream": "tape"})
        == before + 1
    )
    assert (
        v("bars_endpoint_source_tier_total", {"endpoint_group": "klines", "stream": "evil-tier"})
        == 0
    )
    assert v("bars_endpoint_rows_returned_total", {"endpoint_group": "klines"}) == rows_before + 3
    p0 = v("bars_endpoint_param_rejected_total", {"reason": "invalid"})
    bm.record_param_rejected("invalid")
    bm.record_param_rejected("../../etc")
    assert v("bars_endpoint_param_rejected_total", {"reason": "invalid"}) == p0 + 1
    assert v("bars_endpoint_param_rejected_total", {"reason": "../../etc"}) == 0


class UndefinedTableError(Exception):
    """Shaped like `asyncpg.exceptions.UndefinedTableError` (a `PostgresError`): not an
    OSError/ConnectionError/TimeoutError, which is what LazyPgWire re-raises for a missing
    `bars_time`. `bars` may not import asyncpg (ADR-0003), so the fake mirrors its shape."""

    sqlstate = "42P01"


def test_reader_degrades_on_driver_query_error_and_counts_it() -> None:
    from prometheus_client import REGISTRY

    def v(reason: str) -> float:
        got = REGISTRY.get_sample_value("bars_tape_read_degraded_total", {"reason": reason})
        return float(got or 0.0)

    before = (v("query_error"), v("timeout"), v("connection"))
    assert _read(_Fetch([], exc=UndefinedTableError('relation "bars_time" does not exist'))) == []
    assert _read(_Fetch([], exc=TimeoutError())) == []
    assert _read(_Fetch([], exc=ConnectionResetError())) == []
    assert (v("query_error"), v("timeout"), v("connection")) == tuple(b + 1 for b in before)


def test_reader_never_swallows_cancellation() -> None:
    import pytest

    with pytest.raises(asyncio.CancelledError):
        _read(_Fetch([], exc=asyncio.CancelledError()))
