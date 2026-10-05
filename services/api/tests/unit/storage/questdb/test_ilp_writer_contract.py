"""Guard suite for the explicit `IlpWriter` contract (E49-K01-F2, #1856).

Cluster storage-writer: #1835 (lone-producer deadlock), #1636 (untyped error
for a row without the designated timestamp), #1701 (rows lost before
readiness). Each test pins one contract clause from the module docstring.
Deterministic: injected fake clock, `asyncio.Event` gates, no sleeps.
"""

from __future__ import annotations

import asyncio

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.storage.errors import (
    IlpRowError,
    InvalidSymbol,
    MissingDesignatedTimestamp,
    StorageTierUnavailable,
    UnknownIlpTable,
)
from candleviewer.storage.questdb.ilp_writer import DEFAULT_STOP_TIMEOUT_S, IlpWriter
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS, TRADES_SCHEMA

_NEVER = 1e9


# Deadlock guards fail in seconds, not by hanging, if the self-flush regresses.
_GUARD_S = 2.0


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Sink:
    """In-memory transport; `gate` (when set) stalls writes until opened."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.writes = 0
        self.closed = False
        self.gate: asyncio.Event | None = None
        self.entered = asyncio.Event()
        self.yields_per_write: list[int] = []
        self.fail_next = 0
        self.connects = 0
        self.torn_pending = False  # a write was cut mid-line on the live connection

    async def connect(self) -> None:
        self.connects += 1
        self.torn_pending = False  # a fresh connection starts on a line boundary

    async def write(self, data: bytes) -> None:
        self.entered.set()
        if self.gate is not None:
            try:
                await self.gate.wait()
            except asyncio.CancelledError:
                self.torn_pending = True  # half the bytes may be on the wire
                raise
        if self.torn_pending:
            self.lines.append("TORN-LINE-CONCATENATED")
        if self.yields_per_write:
            for _ in range(self.yields_per_write[self.writes % len(self.yields_per_write)]):
                await asyncio.sleep(0)
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ConnectionError("sink down")
        self.writes += 1
        self.lines.extend(data.decode().splitlines())

    async def close(self) -> None:
        self.closed = True


def _row(i: int, **over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "price": 1.0,
        "size": 1.0,
        "trade_id": str(i),
        "ts": i,
    }
    row.update(over)
    return row


def _writer(sink: _Sink, *, cap: int = 4, flush_rows: int = 1000) -> IlpWriter:
    return IlpWriter(
        sink,
        {"trades": TRADES_SCHEMA},
        max_queue_rows=cap,
        flush_rows=flush_rows,
        flush_interval_s=_NEVER,
        clock=_FakeClock(),
    )


def _trade_ids(sink: _Sink) -> list[str]:
    return [line.split('trade_id="')[1].split('"')[0] for line in sink.lines]


async def test_lone_producer_full_queue_never_deadlocks() -> None:
    """#1835: cap < flush_rows, single producer — must self-flush, not hang."""
    sink = _Sink()
    writer = _writer(sink, cap=2)
    await writer.start()
    for i in range(0, 10, 2):
        await asyncio.wait_for(writer.write_rows("trades", [_row(i), _row(i + 1)], "ts"), _GUARD_S)
    assert writer.queue_full_total == 4
    await writer.stop()
    assert _trade_ids(sink) == [str(i) for i in range(10)]


async def test_batch_larger_than_queue_completes() -> None:
    sink = _Sink()
    writer = _writer(sink, cap=3)
    await writer.start()
    await writer.write_rows("trades", [_row(0)], "ts")
    await asyncio.wait_for(
        writer.write_rows("trades", [_row(i) for i in range(1, 11)], "ts"), _GUARD_S
    )
    assert writer.total_buffered == 10  # admitted into the self-flushed (empty) queue
    await writer.stop()
    assert len(sink.lines) == 11


async def test_slow_sink_backpressure_visible_and_nothing_lost() -> None:
    sink = _Sink()
    sink.gate = asyncio.Event()
    writer = _writer(sink, cap=4)
    await writer.start()
    producers = [
        asyncio.ensure_future(
            writer.write_rows("trades", [_row(p * 10 + k) for k in range(3)], "ts")
        )
        for p in range(5)
    ]
    await asyncio.wait_for(sink.entered.wait(), _GUARD_S)
    assert writer.queue_full_total >= 1  # backpressure observed while the sink stalls
    assert not all(p.done() for p in producers)  # callers are parked, not dropped
    sink.gate.set()
    await asyncio.wait_for(asyncio.gather(*producers), _GUARD_S)
    await writer.stop()
    expected = sorted(str(p * 10 + k) for p in range(5) for k in range(3))
    assert sorted(_trade_ids(sink)) == expected


@settings(max_examples=60, deadline=None)
@given(
    batches=st.lists(st.integers(min_value=1, max_value=7), min_size=1, max_size=12),
    stalls=st.lists(st.integers(min_value=0, max_value=4), min_size=1, max_size=6),
    producers=st.integers(min_value=1, max_value=4),
    cap=st.integers(min_value=1, max_value=6),
)
def test_zero_rows_lost_under_arbitrary_stalls(
    batches: list[int], stalls: list[int], producers: int, cap: int
) -> None:
    async def scenario() -> tuple[list[str], list[str]]:
        sink = _Sink()
        sink.yields_per_write = stalls
        writer = _writer(sink, cap=cap, flush_rows=3)
        await writer.start()
        expected: list[str] = []
        counter = 0

        async def produce(pid: int) -> None:
            nonlocal counter
            for size in batches[pid::producers]:
                rows = []
                for _ in range(size):
                    rows.append(_row(counter))
                    expected.append(str(counter))
                    counter += 1
                await writer.write_rows("trades", rows, "ts")

        await asyncio.wait_for(asyncio.gather(*(produce(p) for p in range(producers))), _GUARD_S)
        await writer.stop()
        return sorted(_trade_ids(sink)), sorted(expected)

    got, expected = asyncio.run(scenario())
    assert got == expected  # every row exactly once


@pytest.mark.parametrize(
    ("bad", "err"),
    [
        ({"ts": None}, MissingDesignatedTimestamp),
        ({"ts": "nope"}, MissingDesignatedTimestamp),
        ({"ts": True}, MissingDesignatedTimestamp),
        ({"ts": -1}, MissingDesignatedTimestamp),
        ({"symbol": ""}, InvalidSymbol),
        ({"symbol": 7}, InvalidSymbol),
    ],
)
async def test_bad_row_rejected_before_enqueue(
    bad: dict[str, object], err: type[Exception]
) -> None:
    sink = _Sink()
    writer = _writer(sink)
    await writer.start()
    with pytest.raises(err):
        await writer.write_rows("trades", [_row(0), _row(1, **bad), _row(2)], "ts")
    assert writer.total_buffered == 0  # whole batch rejected, nothing poisoned
    await writer.write_rows("trades", [_row(3)], "ts")
    await writer.stop()
    assert _trade_ids(sink) == ["3"]


async def test_missing_ts_key_raises_typed_error() -> None:
    """#1636: was a bare KeyError."""
    writer = _writer(_Sink())
    row = _row(0)
    del row["ts"]
    with pytest.raises(MissingDesignatedTimestamp) as info:
        await writer.write_rows("trades", [row], "ts")
    assert isinstance(info.value, IlpRowError)
    assert info.value.code == "STORAGE_ILP_MISSING_DESIGNATED_TS"


async def test_unknown_table_typed_and_keyerror_compatible() -> None:
    writer = _writer(_Sink())
    with pytest.raises(KeyError):
        await writer.write_rows("nope", [_row(0)], "ts")
    with pytest.raises(UnknownIlpTable):
        await writer.write_rows("nope", [], "ts")


async def test_empty_batch_is_a_noop() -> None:
    writer = _writer(_Sink())
    await writer.write_rows("trades", [], "ts")
    assert writer.total_buffered == 0


async def test_cancellation_mid_flush_preserves_acked_rows() -> None:
    sink = _Sink()
    writer = _writer(sink)
    await writer.start()
    await writer.write_rows("trades", [_row(0), _row(1)], "ts")  # acknowledged
    sink.gate = asyncio.Event()
    flushing = asyncio.ensure_future(writer.flush(None))
    await sink.entered.wait()
    assert writer.total_buffered == 0  # in flight
    flushing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await flushing
    assert writer.total_buffered == 2  # requeued, not lost
    assert writer.queue_depth("trades") == 2
    sink.gate = None
    await writer.write_rows("trades", [_row(2)], "ts")
    await writer.stop()
    assert _trade_ids(sink) == ["0", "1", "2"]  # order preserved, exactly once


async def test_close_drains_then_refuses_writes() -> None:
    sink = _Sink()
    writer = _writer(sink)
    await writer.start()
    await writer.write_rows("trades", [_row(0), _row(1)], "ts")
    await writer.stop(timeout_s=5)
    assert _trade_ids(sink) == ["0", "1"]
    assert sink.closed
    assert not writer.is_ready
    with pytest.raises(StorageTierUnavailable):
        await writer.write_rows("trades", [_row(2)], "ts")
    with pytest.raises(StorageTierUnavailable):
        await writer.ready(timeout_s=1)
    await writer.stop()  # idempotent


async def test_close_drain_timeout_raises_and_keeps_rows() -> None:
    sink = _Sink()
    writer = _writer(sink)
    await writer.start()
    await writer.write_rows("trades", [_row(0)], "ts")
    sink.gate = asyncio.Event()  # never opened: sink hangs
    with pytest.raises(StorageTierUnavailable):
        await writer.stop(timeout_s=0.01)
    assert writer.total_buffered == 1  # timed-out drain lost nothing
    assert sink.closed


async def test_failed_flush_requeues_and_raises_typed() -> None:
    sink = _Sink()
    writer = _writer(sink, flush_rows=1)
    await writer.start()
    sink.fail_next = 1
    with pytest.raises(StorageTierUnavailable):
        await writer.write_rows("trades", [_row(0)], "ts")
    assert writer.total_buffered == 1
    assert not writer.is_ready
    await writer.stop()  # reconnects and drains
    assert _trade_ids(sink) == ["0"]


async def test_readiness_waits_for_connect_and_times_out() -> None:
    writer = _writer(_Sink())
    assert not writer.is_ready
    with pytest.raises(StorageTierUnavailable):
        await writer.ready(timeout_s=0.01)
    waiter = asyncio.ensure_future(writer.ready(timeout_s=5))
    await writer.start()
    await waiter
    assert writer.is_ready


async def test_interval_flush_driven_by_injected_clock() -> None:
    sink = _Sink()
    clock = _FakeClock()
    writer = IlpWriter(
        sink, {"trades": TRADES_SCHEMA}, flush_rows=1000, flush_interval_s=0.1, clock=clock
    )
    await writer.start()
    await writer.write_rows("trades", [_row(0)], "ts")
    assert sink.writes == 0
    clock.now = 0.1
    await writer.write_rows("trades", [_row(1)], "ts")
    assert sink.writes == 1
    assert writer.total_buffered == 0


def test_max_queue_rows_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_queue_rows"):
        IlpWriter(_Sink(), {"trades": TRADES_SCHEMA}, max_queue_rows=0)


async def test_cancelled_flush_reconnects_and_resends_whole_batch() -> None:
    sink = _Sink()
    writer = _writer(sink)
    await writer.start()
    await writer.write_rows("trades", [_row(0), _row(1)], "ts")
    sink.gate = asyncio.Event()
    flushing = asyncio.ensure_future(writer.flush(None))
    await sink.entered.wait()
    flushing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await flushing
    assert not writer.is_ready  # marked disconnected
    assert sink.closed  # transport closed
    assert sink.torn_pending
    sink.gate = None
    connects_before = sink.connects
    await writer.flush(None)
    assert sink.connects == connects_before + 1  # reconnected
    assert writer.is_ready
    assert "TORN-LINE-CONCATENATED" not in sink.lines
    assert _trade_ids(sink) == ["0", "1"]  # whole batch resent


async def test_stop_default_drain_is_bounded_and_reports_buffered_rows() -> None:
    class _Down(_Sink):
        async def connect(self) -> None:
            raise ConnectionError("down")

    sink = _Down()
    writer = _writer(sink)
    writer._connected = True
    await writer.write_rows("trades", [_row(0), _row(1)], "ts")
    writer._connected = False
    with pytest.raises(StorageTierUnavailable, match="2 rows remain buffered"):
        await writer.stop(timeout_s=0.05)
    assert writer.total_buffered == 2


def test_default_stop_timeout_is_bounded() -> None:
    import inspect

    default = inspect.signature(IlpWriter.stop).parameters["timeout_s"].default
    assert default == DEFAULT_STOP_TIMEOUT_S
    assert 0 < DEFAULT_STOP_TIMEOUT_S <= 60


def test_every_ilp_table_has_dedup_keys_in_schema_doc() -> None:
    """Resend after failure/cancel is only safe with `DEDUP UPSERT KEYS` (contract 5)."""
    import re
    from pathlib import Path

    doc = next(
        q / "docs/plan/21-database-schema.md"
        for q in Path(__file__).resolve().parents
        if (q / "docs/plan/21-database-schema.md").exists()
    ).read_text(encoding="utf-8")
    section = doc[doc.index("## 4.") :] if "## 4." in doc else doc
    deduped = {
        m.group(1)
        for m in re.finditer(
            r"CREATE TABLE (\w+)\s*\((.*?)DEDUP UPSERT KEYS", section, flags=re.DOTALL
        )
    }
    missing = [name for name in ALL_SCHEMAS if name not in deduped and not name.startswith("bars_")]
    assert missing == [], f"ILP tables without DEDUP UPSERT KEYS in the schema doc: {missing}"
