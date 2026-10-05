"""Unit tests for `candleviewer.storage.questdb.ilp_writer` (E07-T03).

Covers: golden ILP line serialisation (`SYMBOL` -> tag, else -> field),
batch/flush trigger logic (5000 rows vs 100 ms) with a fake clock, and
backpressure at queue-full (never drops, always awaits).
"""

from __future__ import annotations

import asyncio
import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

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


def test_serialize_ilp_line_hostile_tag_value_stays_one_line() -> None:
    schema = TableSchema(name="t", tag_columns=("symbol",))
    hostile = "A\nB\rC,D E=F"
    line = serialize_ilp_line(schema, {"symbol": hostile}, ts_us=1)
    assert line.count("\n") == 0
    assert line.count("\r") == 0
    assert r"\n" in line
    assert r"\r" in line


def test_serialize_ilp_line_hostile_string_field_stays_one_line() -> None:
    schema = TableSchema(name="t", tag_columns=(), string_field_columns=("note",))
    hostile = 'A\nB\rC"D\\E'
    line = serialize_ilp_line(schema, {"note": hostile}, ts_us=1)
    assert line.count("\n") == 0
    assert line.count("\r") == 0
    assert r"\n" in line
    assert r"\r" in line
    assert '\\"' in line


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
async def test_write_rows_designated_ts_not_emitted_as_field() -> None:
    # Regression (PR #1630): `ts` was serialised both as a `ts=<n>i` LONG field
    # and as the line timestamp; QuestDB used the field and stored 1970 dates.
    transport = _FakeTransport()
    writer = IlpWriter(transport, {"trades": TRADES_SCHEMA}, flush_rows=1)
    await writer.start()
    row = {"symbol": "BTCUSDT", "price": 1.0, "trade_id": "t", "ts": 1_700_000_000_000_000}
    await writer.write_rows("trades", [row], "ts")
    line = transport.written[0].decode()
    assert " ts=" not in line and ",ts=" not in line
    assert line.rstrip().endswith(" 1700000000000000000")
    assert row["ts"] == 1_700_000_000_000_000  # caller's dict not mutated


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

    gate = asyncio.Event()
    real_write = transport.write

    async def gated_write(data: bytes) -> None:
        await gate.wait()
        await real_write(data)

    transport.write = gated_write  # type: ignore[method-assign]  # stall the sink
    blocked = asyncio.ensure_future(writer.write_rows("trades", [row], "ts"))
    for _ in range(5):
        await asyncio.sleep(0)
    assert not blocked.done()  # queue full + slow sink -> caller is awaiting, not dropped

    gate.set()
    await asyncio.wait_for(blocked, timeout=1.0)
    await writer.flush("trades")  # drain the 3rd row too — nothing left buffered
    assert writer.rows_written_total == 3  # every row eventually written, none dropped


@pytest.mark.asyncio
async def test_write_rows_lone_producer_full_queue_self_flushes_no_deadlock() -> None:
    """Regression (E07-Q03 harness): with `max_queue_rows < flush_rows` and a
    single producer, a full queue used to wait on an Event only another
    flusher could set — so the lone producer hung forever."""
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
    for _ in range(5):
        await asyncio.wait_for(writer.write_rows("trades", [row, row], "ts"), timeout=1.0)
    # an oversized batch into an empty queue is admitted, not parked forever
    await writer.flush(None)
    await asyncio.wait_for(writer.write_rows("trades", [row] * 3, "ts"), timeout=1.0)
    await writer.stop()
    assert writer.rows_written_total == 13


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
    writer = IlpWriter(transport, {"trades": TRADES_SCHEMA}, rng=random.Random(1234))  # noqa: S311 - jitter, not crypto
    await writer.start()
    assert transport.connected is True
    assert writer.write_errors_total == 2
    # Jittered: base delays 0.5, 1.0 each multiplied by a factor in [0.5, 1.5].
    assert len(sleeps) == 2
    assert 0.25 <= sleeps[0] <= 0.75
    assert 0.5 <= sleeps[1] <= 1.5


def test_jittered_delay_grows_exponentially_and_stays_capped() -> None:
    transport = _FakeTransport()
    writer = IlpWriter(transport, {"trades": TRADES_SCHEMA}, rng=random.Random(42))  # noqa: S311 - jitter, not crypto
    base_delays = [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]
    for base in base_delays:
        writer._reconnect_delay_s = base
        delay = writer._jittered_delay_s()
        assert base * 0.5 <= delay <= min(base * 1.5, 30.0)
        assert delay <= 30.0


def test_jittered_delay_sequences_differ_across_seeds() -> None:
    transport = _FakeTransport()
    writer_a = IlpWriter(transport, {"trades": TRADES_SCHEMA}, rng=random.Random(1))  # noqa: S311 - jitter, not crypto
    writer_b = IlpWriter(transport, {"trades": TRADES_SCHEMA}, rng=random.Random(2))  # noqa: S311 - jitter, not crypto
    base_delays = [0.5, 1.0, 2.0, 4.0, 8.0]
    seq_a: list[float] = []
    seq_b: list[float] = []
    for base in base_delays:
        writer_a._reconnect_delay_s = base
        writer_b._reconnect_delay_s = base
        seq_a.append(writer_a._jittered_delay_s())
        seq_b.append(writer_b._jittered_delay_s())
    assert seq_a != seq_b


def test_jittered_delay_same_seed_is_reproducible() -> None:
    transport = _FakeTransport()
    writer_a = IlpWriter(transport, {"trades": TRADES_SCHEMA}, rng=random.Random(7))  # noqa: S311 - jitter, not crypto
    writer_b = IlpWriter(transport, {"trades": TRADES_SCHEMA}, rng=random.Random(7))  # noqa: S311 - jitter, not crypto
    writer_a._reconnect_delay_s = 4.0
    writer_b._reconnect_delay_s = 4.0
    assert writer_a._jittered_delay_s() == writer_b._jittered_delay_s()


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


@given(st.text(min_size=0, max_size=40))
def test_serialize_ilp_line_arbitrary_tag_text_is_one_line(text: str) -> None:
    # ILP line boundaries are ASCII newline/carriage-return only; other
    # Unicode line separators are not special to the ILP wire format.
    schema = TableSchema(name="t", tag_columns=("symbol",))
    line = serialize_ilp_line(schema, {"symbol": text}, ts_us=1)
    assert "\n" not in line
    assert "\r" not in line


@given(st.text(min_size=0, max_size=40))
def test_serialize_ilp_line_arbitrary_string_field_text_is_one_line(text: str) -> None:
    schema = TableSchema(name="t", tag_columns=(), string_field_columns=("note",))
    line = serialize_ilp_line(schema, {"note": text}, ts_us=1)
    assert "\n" not in line
    assert "\r" not in line


@pytest.mark.asyncio
async def test_connect_holds_writes_until_readiness_probe_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Port accepts before the ILP listener is live: no batch may be sent
    until the readiness probe succeeds (regression for #1701)."""

    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    transport = _FakeTransport()
    results = iter([False, False, True])
    calls: list[int] = []

    async def probe() -> bool:
        calls.append(len(transport.written))
        return next(results)

    writer = IlpWriter(transport, {"trades": TRADES_SCHEMA}, flush_rows=1, readiness_probe=probe)
    await writer.start()
    assert len(calls) == 3
    assert transport.written == []
    row = {"symbol": "BTCUSDT", "price": 1.0, "trade_id": "t", "ts": 1_700_000_000_000_000}
    await writer.write_rows("trades", [row], "ts")
    assert len(transport.written) == 1
    assert writer.rows_written_total == 1


@pytest.mark.asyncio
async def test_reconnect_mid_run_reruns_readiness_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A write failure drops the connection; the next flush must re-probe
    before sending (chaos S1 shape, #1701)."""

    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    transport = _FakeTransport()
    probes: list[int] = []

    async def probe() -> bool:
        probes.append(1)
        return True

    writer = IlpWriter(transport, {"trades": TRADES_SCHEMA}, flush_rows=1, readiness_probe=probe)
    await writer.start()
    assert len(probes) == 1
    writer._connected = False  # simulate drop after a failed write
    row = {"symbol": "BTCUSDT", "price": 1.0, "trade_id": "t", "ts": 1_700_000_000_000_000}
    await writer.write_rows("trades", [row], "ts")
    assert len(probes) == 2
    assert writer.rows_written_total == 1


@pytest.mark.asyncio
async def test_reconcile_reports_sent_vs_committed_gap() -> None:
    transport = _FakeTransport()
    committed = [10]

    async def counter() -> int:
        return committed[0]

    writer = IlpWriter(
        transport, {"trades": TRADES_SCHEMA}, flush_rows=1, committed_counter=counter
    )
    await writer.start()
    row = {"symbol": "BTCUSDT", "price": 1.0, "trade_id": "t", "ts": 1_700_000_000_000_000}
    await writer.write_rows("trades", [row], "ts")
    assert await writer.reconcile() == 1
    assert writer.unreconciled_rows == 1
    committed[0] = 11
    assert await writer.reconcile() == 0
    assert writer.unreconciled_rows == 0


@pytest.mark.asyncio
async def test_reconcile_baseline_set_once_and_kept_across_reconnect() -> None:
    transport = _FakeTransport()
    committed = [100]
    calls = [0]

    async def counter() -> int:
        calls[0] += 1
        return committed[0]

    writer = IlpWriter(
        transport, {"trades": TRADES_SCHEMA}, flush_rows=1, committed_counter=counter
    )
    await writer.start()
    row = {"symbol": "BTCUSDT", "price": 1.0, "trade_id": "t", "ts": 1_700_000_000_000_000}
    await writer.write_rows("trades", [row], "ts")
    writer._connected = False  # drop, then reconnect on next write
    await writer.write_rows("trades", [row], "ts")
    committed[0] = 101  # only one of two rows landed
    before = calls[0]
    assert await writer.reconcile() == 1  # baseline stayed 100
    assert calls[0] == before + 1  # reconcile read once; no re-baseline


@pytest.mark.asyncio
async def test_build_hot_tier_writer_wires_guards_and_exports_gap() -> None:
    from candleviewer.observability.metrics import Metrics
    from candleviewer.storage.questdb.wiring import build_hot_tier_writer, run_reconcile_loop

    class Conn:
        n = 5

        async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
            return [{"n": self.n}]

    conn = Conn()
    writer = build_hot_tier_writer(_FakeTransport(), {"trades": TRADES_SCHEMA}, conn, flush_rows=1)
    await writer.start()
    row = {"symbol": "BTCUSDT", "price": 1.0, "trade_id": "t", "ts": 1_700_000_000_000_000}
    await writer.write_rows("trades", [row], "ts")
    metrics = Metrics("demo")
    await run_reconcile_loop(writer, metrics, interval_s=0, iterations=1)
    assert writer.unreconciled_rows == 1
    assert "questdb_ilp_unreconciled_rows" in metrics._metrics
