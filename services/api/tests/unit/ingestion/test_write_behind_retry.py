"""#1918 regression: a failed hot-tier write is requeued with backoff, never discarded.

Chaos scenario 11 (E08-Q03, C-13.6 #10) asserts the same end-to-end; these
unit tests pin it without the chaos suite (fake writer, fake sleep, no I/O).
"""

from __future__ import annotations

from collections.abc import Sequence

from hypothesis import given
from hypothesis import strategies as st

from candleviewer.api.health import make_health_router
from candleviewer.health_wiring import hot_tier_write_behind_state
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.metrics import trade_writes_dropped_total
from candleviewer.ingestion.write_behind import WriteBehindBuffer
from candleviewer.observability.health_probes import ComponentState


class _Sleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, s: float) -> None:
        self.delays.append(s)


class _Writer:
    """Fails the next `fail` writes, then persists."""

    def __init__(self, fail: int = 0) -> None:
        self.fail = fail
        self.rows: list[tuple[str, int]] = []

    async def write(self, rows: Sequence[tuple[str, int]]) -> None:
        if self.fail > 0:
            self.fail -= 1
            raise OSError("questdb down")
        self.rows.extend(rows)


def _buf(maxsize: int = 100, sleep: _Sleep | None = None) -> WriteBehindBuffer[tuple[str, int]]:
    return WriteBehindBuffer(
        table="trades",
        maxsize=maxsize,
        dropped=trade_writes_dropped_total,
        key=lambda r: r,
        sleep=sleep or _Sleep(),
        rand=lambda: 0.0,
    )


async def _drain(buf: WriteBehindBuffer[tuple[str, int]], w: _Writer, batch: int = 3) -> None:
    """The streams' drain step, minus the stream."""
    rows = await buf.take(batch)
    try:
        await w.write(rows)
    except OSError:
        buf.requeue(rows)
        await buf.backoff()
        return
    buf.succeeded()


def _outage_count() -> float:
    return float(trade_writes_dropped_total.labels(reason="outage")._value.get())  # type: ignore[attr-defined]  # test-only peek at the prometheus child


async def test_write_behind_failing_writer_recovers_all_rows_once_in_order() -> None:
    buf, w = _buf(), _Writer(fail=3)
    rows = [("BTCUSDT", i) for i in range(10)]
    for r in rows:
        buf.put(r)
    while buf.qsize():
        await _drain(buf, w)
    assert w.rows == rows
    assert not buf.degraded and buf.evicted == 0


async def test_write_behind_backoff_doubles_with_jitter_and_caps() -> None:
    sleep = _Sleep()
    buf, w = _buf(sleep=sleep), _Writer(fail=10)
    buf.put(("BTCUSDT", 1))
    for _ in range(10):
        await _drain(buf, w)
    assert sleep.delays[:4] == [0.1, 0.2, 0.4, 0.8]
    assert max(sleep.delays) == 10.0  # BACKOFF_CAP_S
    jittered = WriteBehindBuffer(
        table="t", maxsize=1, dropped=trade_writes_dropped_total, key=lambda r: r, rand=lambda: 1.0
    )
    jittered.requeue([("X", 1)])
    assert jittered.delay_s() == 0.125


async def test_write_behind_sustained_outage_evicts_oldest_counted_and_hole_recorded() -> None:
    buf, w = _buf(maxsize=4), _Writer(fail=1_000)
    before = _outage_count()
    for i in range(4):
        buf.put(("BTCUSDT", i))
    await _drain(buf, w)  # fails: degraded from here on
    for i in range(4, 7):
        buf.put(("BTCUSDT", i))
    buf.flush_metrics()  # counters are batched off the reader path (#1918 r2)
    assert buf.evicted == 3 and _outage_count() - before == 3
    assert buf.lost_ranges("BTCUSDT") == [Range(0, 3)]
    assert buf.lost_ranges("ETHUSDT") == []
    assert hot_tier_write_behind_state([buf]).state is ComponentState.DEGRADED


async def test_write_behind_health_degraded_during_outage_ok_after() -> None:
    buf, w = _buf(), _Writer(fail=1)
    assert hot_tier_write_behind_state([]).state is ComponentState.NOT_DEPLOYED
    buf.put(("BTCUSDT", 1))
    await _drain(buf, w)
    assert hot_tier_write_behind_state([buf]).state is ComponentState.DEGRADED
    await _drain(buf, w)
    assert hot_tier_write_behind_state([buf]).state is ComponentState.HEALTHY


def test_readyz_reports_hot_tier_write_behind_degraded_then_ok() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from candleviewer.settings import Settings

    buf = _buf()
    app = FastAPI()
    app.include_router(make_health_router(Settings(), write_behind=lambda: [buf]))
    client = TestClient(app)
    buf.requeue([("BTCUSDT", 1)])
    body = client.get("/readyz")
    assert body.status_code == 200  # degraded, not fatal
    assert body.json()["status"] == "degraded"
    assert body.json()["checks"] == [{"name": "hot_tier_write_behind", "ok": False}]
    buf.succeeded()
    body = client.get("/readyz").json()
    assert body["status"] == "ok" and body["checks"][0]["ok"] is True


@given(
    n=st.integers(1, 40),
    maxsize=st.integers(1, 8),
    script=st.lists(st.booleans(), min_size=1, max_size=60),
)
async def test_write_behind_property_persisted_union_evicted_is_published(
    n: int, maxsize: int, script: list[bool]
) -> None:
    evicted: list[tuple[str, int]] = []
    buf: WriteBehindBuffer[tuple[str, int]] = WriteBehindBuffer(
        table="trades",
        maxsize=maxsize,
        dropped=trade_writes_dropped_total,
        key=lambda r: (evicted.append(r), r)[1],  # key() runs once per eviction
        sleep=_Sleep(),
        rand=lambda: 0.0,
    )
    published = [("BTCUSDT", i) for i in range(n)]
    persisted: list[tuple[str, int]] = []
    it = iter(published)
    for fail in script + [False] * (n + 2):
        nxt = next(it, None)
        if nxt is not None:
            buf.put(nxt)
        if buf.qsize():
            rows = await buf.take(3)
            arriving = next(it, None)  # publishes land while the write is in flight
            if arriving is not None:
                buf.put(arriving)
            if fail:
                buf.requeue(rows)
            else:
                persisted.extend(rows)
                buf.succeeded()
    while buf.qsize():
        persisted.extend(await buf.take(3))
    assert len(persisted) == len(set(persisted))
    assert sorted(persisted + evicted) == published
    assert persisted == sorted(persisted)
    assert buf.evicted == len(evicted)
    lost = buf.lost_ranges("BTCUSDT")
    assert all(any(r.start_us <= ts < r.end_us for r in lost) for _, ts in evicted)


async def test_book_stream_failed_batch_requeues_unwritten_suffix_in_order() -> None:
    from candleviewer.bus.bus import Bus
    from candleviewer.orderbook_wiring import BookStream
    from candleviewer.storage.repositories.rows import BookDeltaRow, BookSnapshotRow

    written: list[object] = []
    fail = {"snap": 2}

    class W:
        async def write_book_deltas(self, rows: Sequence[BookDeltaRow]) -> None:
            written.extend(rows)

        async def write_book_snapshot(self, row: BookSnapshotRow) -> None:
            if fail["snap"]:
                fail["snap"] -= 1
                raise OSError("questdb down")
            written.append(row)

    async def _noop(_t: str) -> None:
        return None

    sleep = _Sleep()
    stream = BookStream(
        bus=Bus(),
        env="live",
        set_desired=lambda _t: None,
        parse_frame=lambda _f: None,
        topic_for=lambda s, d: f"orderbook.{d}.{s}",
        resubscribe=_noop,
        is_listed=lambda _s: True,
        touch=lambda _t: None,
        writer=W(),
        rand=lambda: 0.0,
        write_sleep=sleep,
    )
    d1 = BookDeltaRow(1, "BTCUSDT", 1, "bid", "1", "1")
    snap = BookSnapshotRow(ts_us=2, symbol="BTCUSDT", seq=2, bids=(), asks=())
    d2 = BookDeltaRow(3, "BTCUSDT", 3, "ask", "2", "1")
    for r in (d1, snap, d2):
        stream._enqueue(r)
    assert await stream.drain_writes() == 1  # d1 persisted, then the snapshot fails
    assert stream.write_behind.qsize() == 2 and stream.write_behind.degraded
    assert await stream.drain_writes() == 0
    assert sleep.delays == [0.1, 0.2]
    assert await stream.drain_writes() == 2
    assert written == [d1, snap, d2]  # exactly once, in order
    assert not stream.write_behind.degraded
    assert await _no_writer_drain() == 1


async def _no_writer_drain() -> int:
    from candleviewer.bus.bus import Bus
    from candleviewer.orderbook_wiring import BookStream
    from candleviewer.storage.repositories.rows import BookDeltaRow

    async def _noop(_t: str) -> None:
        return None

    stream = BookStream(
        bus=Bus(),
        env="live",
        set_desired=lambda _t: None,
        parse_frame=lambda _f: None,
        topic_for=lambda s, d: f"orderbook.{d}.{s}",
        resubscribe=_noop,
        is_listed=lambda _s: True,
        touch=lambda _t: None,
    )
    stream.write_behind.put(BookDeltaRow(1, "BTCUSDT", 1, "bid", "1", "1"))
    return await stream.drain_writes()


async def test_write_behind_lost_run_closes_on_next_success_and_reopens() -> None:
    buf = _buf(maxsize=2)
    for i in range(4):  # evicts 0, 1 -> one open run
        buf.put(("BTCUSDT", i))
    assert buf.lost_ranges("BTCUSDT") == [Range(0, 2)]
    buf.succeeded(await buf.take(2))  # closes it
    for i in range(10, 13):  # evicts 10 -> a new, separate run
        buf.put(("BTCUSDT", i))
    assert buf.lost_ranges("BTCUSDT") == [Range(0, 2), Range(10, 11)]


async def test_write_behind_closed_runs_capped_oldest_merged_and_counted() -> None:
    from candleviewer.ingestion.metrics import write_behind_lost_runs_truncated_total
    from candleviewer.ingestion.write_behind import MAX_LOST_RUNS

    child = write_behind_lost_runs_truncated_total.labels(table="trades")
    before = float(child._value.get())  # type: ignore[attr-defined]  # test-only peek
    buf = _buf(maxsize=1)
    for i in range(MAX_LOST_RUNS + 3):
        buf.put(("BTCUSDT", 10 * i))
        buf.put(("BTCUSDT", 10 * i + 5))  # evicts 10*i
        buf.succeeded(await buf.take(1))
    runs = buf.lost_ranges("BTCUSDT")
    assert len(runs) == MAX_LOST_RUNS
    assert runs[0].start_us == 0  # merged, never hidden
    assert float(child._value.get()) - before == 3  # type: ignore[attr-defined]


async def test_trade_stream_cancelled_write_restores_batch_to_head() -> None:
    import asyncio

    from candleviewer.bus.bus import Bus
    from candleviewer.ingestion.trade_stream import TradeStream

    gate = asyncio.Event()

    class Hang:
        async def write_trades(self, events: Sequence[object]) -> None:
            gate.set()
            await asyncio.Event().wait()

    stream = TradeStream(
        bus=Bus(),
        env="live",
        set_desired=lambda _t: None,
        parse_frame=lambda _f: None,
        topic_for=lambda s: s,
        is_listed=lambda _s: True,
        touch=lambda _t: None,
        writer=Hang(),  # type: ignore[arg-type]  # structural fake, rows unused
    )
    for i in range(3):
        stream.write_behind.put(("BTCUSDT", i))  # type: ignore[arg-type]  # opaque rows
    task = asyncio.create_task(stream.drain_writes())
    await gate.wait()
    task.cancel()
    with __import__("pytest").raises(asyncio.CancelledError):
        await task
    assert stream.write_behind.qsize() == 3 and not stream.write_behind.degraded
    assert await stream.write_behind.take(3) == [("BTCUSDT", i) for i in range(3)]


async def test_book_stream_cancelled_write_restores_unwritten_suffix() -> None:
    import asyncio

    import pytest

    from candleviewer.bus.bus import Bus
    from candleviewer.orderbook_wiring import BookStream
    from candleviewer.storage.repositories.rows import BookDeltaRow, BookSnapshotRow

    gate = asyncio.Event()
    written: list[object] = []

    class W:
        async def write_book_deltas(self, rows: Sequence[BookDeltaRow]) -> None:
            written.extend(rows)

        async def write_book_snapshot(self, row: BookSnapshotRow) -> None:
            gate.set()
            await asyncio.Event().wait()

    async def _noop(_t: str) -> None:
        return None

    stream = BookStream(
        bus=Bus(),
        env="live",
        set_desired=lambda _t: None,
        parse_frame=lambda _f: None,
        topic_for=lambda s, d: f"orderbook.{d}.{s}",
        resubscribe=_noop,
        is_listed=lambda _s: True,
        touch=lambda _t: None,
        writer=W(),
    )
    d1 = BookDeltaRow(1, "BTCUSDT", 1, "bid", "1", "1")
    snap = BookSnapshotRow(ts_us=2, symbol="BTCUSDT", seq=2, bids=(), asks=())
    for r in (d1, snap):
        stream.write_behind.put(r)
    task = asyncio.create_task(stream.drain_writes())
    await gate.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert written == [d1]
    assert await stream.write_behind.take(5) == [snap]


async def test_trade_stream_stop_flushes_pending_drop_counts() -> None:
    from candleviewer.bus.bus import Bus
    from candleviewer.ingestion.trade_stream import TradeStream

    class Never:
        async def write_trades(self, events: Sequence[object]) -> None:
            raise OSError("questdb down")

    stream = TradeStream(
        bus=Bus(),
        env="live",
        set_desired=lambda _t: None,
        parse_frame=lambda _f: None,
        topic_for=lambda s: s,
        is_listed=lambda _s: True,
        touch=lambda _t: None,
        writer=Never(),  # type: ignore[arg-type]  # structural fake
    )
    buf = stream.write_behind
    buf.failures = 1
    before = _outage_count()
    from types import SimpleNamespace

    for i in range(8192 + 5):  # only the key fields are read
        buf.put(SimpleNamespace(symbol="BTCUSDT", ts_event=i))  # type: ignore[arg-type]
    assert _outage_count() == before  # batched, not yet published
    await stream.stop()
    assert _outage_count() - before == 5


async def test_book_stream_stop_flushes_pending_drop_counts() -> None:
    from candleviewer.bus.bus import Bus
    from candleviewer.ingestion.metrics import book_writes_dropped_total
    from candleviewer.orderbook_wiring import BookStream
    from candleviewer.storage.repositories.rows import BookDeltaRow

    def count() -> float:
        return float(book_writes_dropped_total.labels(reason="outage")._value.get())  # type: ignore[attr-defined]  # test-only peek

    async def _noop(_t: str) -> None:
        return None

    stream = BookStream(
        bus=Bus(),
        env="live",
        set_desired=lambda _t: None,
        parse_frame=lambda _f: None,
        topic_for=lambda s, d: f"orderbook.{d}.{s}",
        resubscribe=_noop,
        is_listed=lambda _s: True,
        touch=lambda _t: None,
    )
    buf = stream.write_behind
    buf.failures = 1
    before = count()
    for i in range(8192 + 5):
        buf.put(BookDeltaRow(i, "BTCUSDT", i, "bid", "1", "1"))
    assert count() == before  # batched, not yet published
    await stream.stop()
    assert count() - before == 5
