"""Unit tests for `candleviewer.storage.questdb.ilp_writer` (E07-T03).

Covers: golden ILP line serialisation (`SYMBOL` -> tag, else -> field),
batch/flush trigger logic (5000 rows vs 100 ms) with a fake clock, and
backpressure at queue-full (never drops, always awaits).
"""

from __future__ import annotations

import asyncio

import pytest

from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.questdb.ilp_writer import IlpWriter, TableSchema, serialize_ilp_line
from candleviewer.storage.questdb.schemas import TRADES_SCHEMA


def test_serialize_ilp_line_trades_golden_row() -> None:
    row = {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "tick_dir": "PlusTick",
        "price": 65000.5,
        "size": 0.01,
        "notional": 650.005,
        "trade_id": "abc123",
        "is_block": False,
    }
    line = serialize_ilp_line(TRADES_SCHEMA, row, ts_us=1_700_000_000_000_000)
    assert line.startswith("trades,symbol=BTCUSDT,side=Buy,tick_dir=PlusTick ")
    assert 'trade_id="abc123"' in line
    assert "is_block=false" in line
    assert "price=65000.5" in line
    assert line.endswith(" 1700000000000000000")


def test_serialize_ilp_line_escapes_tag_special_characters() -> None:
    schema = TableSchema(name="t", tag_columns=("symbol",))
    line = serialize_ilp_line(schema, {"symbol": "A B,C=D"}, ts_us=1)
    assert r"symbol=A\ B\,C\=D" in line


def test_serialize_ilp_line_emits_int_and_timestamp_fields() -> None:
    schema = TableSchema(
        name="t",
        tag_columns=("symbol",),
        timestamp_field_columns=("close_ts",),
    )
    line = serialize_ilp_line(
        schema,
        {"symbol": "BTCUSDT", "seq": 42, "close_ts": 1_700_000_000_000_000},
        ts_us=1,
    )
    assert "seq=42i" in line
    assert "close_ts=1700000000000000t" in line


class _FakeTransport:
    def __init__(self, fail_writes: int = 0) -> None:
        self.connected = False
        self.closed = False
        self.written: list[bytes] = []
        self._fail_writes = fail_writes

    async def connect(self) -> None:
        self.connected = True

    async def write(self, data: bytes) -> None:
        if self._fail_writes > 0:
            self._fail_writes -= 1
            raise ConnectionError("boom")
        self.written.append(data)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_flush_triggers_at_row_threshold() -> None:
    transport = _FakeTransport()
    writer = IlpWriter(transport, {"trades": TRADES_SCHEMA}, flush_rows=3)
    await writer.start()
    rows = [
        {
            "symbol": "BTCUSDT",
            "side": "Buy",
            "price": 1.0,
            "size": 1.0,
            "notional": 1.0,
            "trade_id": str(i),
            "tick_dir": "PlusTick",
            "is_block": False,
            "ts": i,
        }
        for i in range(3)
    ]
    await writer.write_rows("trades", rows, "ts")
    assert len(transport.written) == 1
    assert writer.rows_written_total == 3
    assert writer.queue_depth("trades") == 0


@pytest.mark.asyncio
async def test_flush_does_not_trigger_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _FakeTransport()
    writer = IlpWriter(transport, {"trades": TRADES_SCHEMA}, flush_rows=100, flush_interval_s=100.0)
    await writer.start()
    row = {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "price": 1.0,
        "size": 1.0,
        "notional": 1.0,
        "trade_id": "1",
        "tick_dir": "PlusTick",
        "is_block": False,
        "ts": 1,
    }
    await writer.write_rows("trades", [row], "ts")
    assert transport.written == []
    assert writer.queue_depth("trades") == 1


@pytest.mark.asyncio
async def test_flush_triggers_on_time_elapsed() -> None:
    transport = _FakeTransport()
    writer = IlpWriter(transport, {"trades": TRADES_SCHEMA}, flush_rows=1000, flush_interval_s=0.01)
    await writer.start()
    row = {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "price": 1.0,
        "size": 1.0,
        "notional": 1.0,
        "trade_id": "1",
        "tick_dir": "PlusTick",
        "is_block": False,
        "ts": 1,
    }
    await writer.write_rows("trades", [row], "ts")
    assert transport.written == []
    await asyncio.sleep(0.02)
    await writer.write_rows("trades", [row], "ts")
    assert len(transport.written) == 1


@pytest.mark.asyncio
async def test_write_rows_applies_backpressure_never_drops() -> None:
    transport = _FakeTransport()
    writer = IlpWriter(
        transport,
        {"trades": TRADES_SCHEMA},
        max_queue_rows=2,
        flush_rows=1000,
        flush_interval_s=1000.0,
    )
    await writer.start()
    row = {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "price": 1.0,
        "size": 1.0,
        "notional": 1.0,
        "trade_id": "1",
        "tick_dir": "PlusTick",
        "is_block": False,
        "ts": 1,
    }
    await writer.write_rows("trades", [row, row], "ts")
    assert writer.queue_depth("trades") == 2

    blocked = asyncio.ensure_future(writer.write_rows("trades", [row], "ts"))
    await asyncio.sleep(0.01)
    assert not blocked.done()  # queue full -> caller is awaiting, not dropped

    await writer.flush("trades")
    await asyncio.wait_for(blocked, timeout=1.0)
    await writer.flush("trades")  # drain the 3rd row too — nothing left buffered
    assert writer.rows_written_total == 3  # every row eventually written, none dropped


@pytest.mark.asyncio
async def test_flush_reraises_and_requeues_on_transport_failure() -> None:
    transport = _FakeTransport(fail_writes=1)
    writer = IlpWriter(transport, {"trades": TRADES_SCHEMA}, flush_rows=1, flush_interval_s=1000.0)
    await writer.start()
    row = {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "price": 1.0,
        "size": 1.0,
        "notional": 1.0,
        "trade_id": "1",
        "tick_dir": "PlusTick",
        "is_block": False,
        "ts": 1,
    }
    with pytest.raises(StorageTierUnavailable):
        await writer.write_rows("trades", [row], "ts")
    assert writer.write_errors_total == 1
    # Row was requeued, not dropped.
    assert writer.queue_depth("trades") == 1


@pytest.mark.asyncio
async def test_start_retries_connect_with_backoff_until_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FlakyTransport(_FakeTransport):
        def __init__(self) -> None:
            super().__init__()
            self._attempts = 0

        async def connect(self) -> None:
            self._attempts += 1
            if self._attempts < 3:
                raise ConnectionRefusedError("not up yet")
            await super().connect()

    sleeps: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    transport = _FlakyTransport()
    writer = IlpWriter(transport, {"trades": TRADES_SCHEMA})
    await writer.start()
    assert transport.connected is True
    assert writer.write_errors_total == 2
    assert sleeps == [0.5, 1.0]


@pytest.mark.asyncio
async def test_stop_flushes_and_closes_transport() -> None:
    transport = _FakeTransport()
    writer = IlpWriter(
        transport, {"trades": TRADES_SCHEMA}, flush_rows=1000, flush_interval_s=1000.0
    )
    await writer.start()
    row = {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "price": 1.0,
        "size": 1.0,
        "notional": 1.0,
        "trade_id": "1",
        "tick_dir": "PlusTick",
        "is_block": False,
        "ts": 1,
    }
    await writer.write_rows("trades", [row], "ts")
    await writer.stop()
    assert len(transport.written) == 1
    assert transport.closed is True
