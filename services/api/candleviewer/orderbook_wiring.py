"""Composition-root wiring (not a module): live order book (E08-S05).

Demand, per-symbol `TieredBook`, bus publish and write-behind.

Wires the venue-neutral `book` module to ingestion. Rules:

* A symbol's `BookEngine` publishes **only while LIVE** (the engine enforces it
  synchronously; the B14 chart supervises). Consumers on
  `{env}.md.{symbol}.book` therefore never see a delta before the snapshot.
* Resync = unsubscribe + subscribe of that one topic through the connection
  manager's shaped `resubscribe` (E08-T04 budget), never a fire-all burst.
* `SNAPSHOT_TIMEOUT`: a snapshot pending longer than `snapshot_timeout_s`
  re-enters `snapshot_pending` (chart) / re-requests (unsupervised).
* Write-behind to QuestDB is a bounded queue that drops oldest, never
  blocking the reader.

Plain code on the hot path (catalogue 1.2, C-2.20): this module never imports
the statechart package. B14 health supervision is an injected
`HealthSupervisor` (`ingestion.book_supervisor.B14BookSupervisor`, built in
`create_app`) that receives lifecycle edges fire-and-forget.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import structlog

from candleviewer.book.models import BookPhase
from candleviewer.book.resync import BookEngine, HealthSink
from candleviewer.book.tiers import DEFAULT_DEPTH, TieredBook
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, Topic, TopicPattern
from candleviewer.exchange.base.models import BookDelta, BookSnapshot
from candleviewer.ingestion.metrics import book_writes_dropped_total, questdb_write_queue_depth
from candleviewer.ingestion.planner import DEFAULT_GRACE_S, DemandTracker
from candleviewer.ingestion.ticker_stream import UnknownSymbolError
from candleviewer.ingestion.watchdog import FeedHealthEvent
from candleviewer.observability.context import spawn
from candleviewer.storage.repositories.rows import BookDeltaRow, BookSnapshotRow

logger = structlog.get_logger(__name__)

WRITE_QUEUE_MAXSIZE = 8192
SNAPSHOT_TIMEOUT_S = 10.0


class BookWriter(Protocol):
    async def write_book_deltas(self, rows: Sequence[BookDeltaRow]) -> None: ...
    async def write_book_snapshot(self, row: BookSnapshotRow) -> None: ...


@dataclass(frozen=True, slots=True)
class BookView:
    """A LIVE book as served by `GET /market/orderbook`."""

    snapshot: BookSnapshot
    stale: bool


def _now_us() -> int:
    return time.time_ns() // 1000


class HealthSupervisor(Protocol):
    """Non-hot B14 supervision, injected by the composition root."""

    async def attach(self, key: str, symbol: str) -> HealthSink: ...
    def detach(self, key: str) -> None: ...


class BookStream:
    def __init__(
        self,
        *,
        bus: Bus,
        env: str,
        set_desired: Callable[[set[str]], None],
        parse_frame: Callable[[str], BookSnapshot | BookDelta | None],
        topic_for: Callable[[str, int], str],
        resubscribe: Callable[[str], Awaitable[None]],
        is_listed: Callable[[str], bool],
        touch: Callable[[str], None],
        clock: Callable[[], float] = time.monotonic,
        now_us: Callable[[], int] = _now_us,
        grace_s: float = DEFAULT_GRACE_S,
        writer: BookWriter | None = None,
        snapshot_timeout_s: float = SNAPSHOT_TIMEOUT_S,
        default_depth: int = DEFAULT_DEPTH,
        supervisor: HealthSupervisor | None = None,
    ) -> None:
        self._bus, self._env = bus, env
        self._set_desired, self._parse = set_desired, parse_frame
        self._topic_for, self._resub = topic_for, resubscribe
        self._is_listed, self._touch = is_listed, touch
        self._now_us, self._writer = now_us, writer
        self._timeout_us = int(snapshot_timeout_s * 1_000_000)
        self._depth = default_depth
        self._demand = DemandTracker(clock, grace_s)
        self._books: dict[str, TieredBook] = {}
        self._first_sub: set[tuple[str, int]] = set()
        self._supervisor = supervisor
        self._keys: dict[str, list[str]] = {}
        self._writes: asyncio.Queue[BookDeltaRow | BookSnapshotRow] = asyncio.Queue(
            maxsize=WRITE_QUEUE_MAXSIZE
        )
        self._tasks: list[asyncio.Task[None]] = []
        self._health = bus.subscribe(
            "book-stream-health",
            TopicPattern(env=env, domain="health", detail="feed"),
            QueuePolicy.NEVER_DROP,
            maxsize=1024,
        )

    # ---- demand ---------------------------------------------------------
    def acquire(self, consumer: str, symbol: str) -> None:
        if not self._is_listed(symbol):
            raise UnknownSymbolError(symbol)
        self._demand.acquire(consumer, symbol)
        self.sync()

    def release(self, consumer: str, symbol: str) -> None:
        self._demand.release(consumer, symbol)
        self.sync()

    def is_listed(self, symbol: str) -> bool:
        return self._is_listed(symbol)

    def sync(self) -> None:
        wanted = self._demand.desired()
        topics: set[str] = set()
        for sym in wanted:
            tb = self._books.get(sym)
            depths = {self._depth} if tb is None else {tb.active.depth}
            if tb is not None and tb.warming is not None:
                depths.add(tb.warming.depth)
            topics |= {self._topic_for(sym, d) for d in depths}
        self._set_desired(topics)
        for gone in set(self._books) - wanted:
            self._drop(gone)

    def _drop(self, symbol: str) -> None:
        self._books.pop(symbol, None)
        for key in self._keys.pop(symbol, []):
            if self._supervisor is not None:
                self._supervisor.detach(key)
        self._first_sub = {k for k in self._first_sub if k[0] != symbol}

    # ---- reads (GET /market/orderbook) -----------------------------------
    def view(self, symbol: str, depth: int) -> BookView | None:
        """The maintained book, only while LIVE at `depth` (else `None`)."""
        tb = self._books.get(symbol)
        if tb is None or depth > tb.active.depth:
            return None
        snap = tb.active.live_snapshot(depth)
        return None if snap is None else BookView(snap, stale=False)

    def phase(self, symbol: str) -> BookPhase | None:
        tb = self._books.get(symbol)
        return None if tb is None else tb.active.phase

    # ---- tier change -------------------------------------------------------
    async def change_depth(self, symbol: str, depth: int) -> None:
        tb = self._books.get(symbol)
        if tb is None:
            self._depth = depth
            return
        await tb.change_depth(depth)
        self.sync()

    # ---- engines ----------------------------------------------------------
    def _make_engine(self, symbol: str) -> Callable[[int, bool], BookEngine]:
        def make(depth: int, muted: bool) -> BookEngine:
            async def publish(obj: object) -> None:
                await self._publish(symbol, obj)

            async def resub() -> None:
                key = (symbol, depth)
                if key not in self._first_sub:  # first subscribe is the demand sync itself
                    self._first_sub.add(key)
                    return
                await self._resub(self._topic_for(symbol, depth))

            eng = BookEngine(
                symbol=symbol, depth=depth, publish=publish, resubscribe=resub, now_us=self._now_us
            )
            eng.muted = muted
            return eng

        return make

    async def _ensure(self, symbol: str) -> TieredBook:
        tb = self._books.get(symbol)
        if tb is not None:
            return tb
        tb = TieredBook(self._make_engine(symbol), self._depth)
        self._books[symbol] = tb
        if self._supervisor is not None:
            key = f"{self._env}:{symbol}:{tb.active.depth}"
            self._keys.setdefault(symbol, []).append(key)
            tb.active.health_sink = await self._supervisor.attach(key, symbol)
        await tb.start()
        return tb

    async def _publish(self, symbol: str, obj: object) -> None:
        topic = Topic(env=self._env, domain="md", symbol=symbol, detail="book")
        await self._bus.publish(topic, obj)
        if isinstance(obj, BookSnapshot):
            self._enqueue(
                BookSnapshotRow(
                    ts_us=obj.ts_event,
                    symbol=symbol,
                    seq=obj.update_id,
                    bids=tuple((str(x.price), str(x.qty)) for x in obj.bids),
                    asks=tuple((str(x.price), str(x.qty)) for x in obj.asks),
                )
            )
        elif isinstance(obj, BookDelta):
            for side, levels in (("bid", obj.bids), ("ask", obj.asks)):
                for lv in levels:
                    self._enqueue(
                        BookDeltaRow(
                            obj.ts_event, symbol, obj.update_id, side, str(lv.price), str(lv.qty)
                        )
                    )

    def _enqueue(self, row: BookDeltaRow | BookSnapshotRow) -> None:
        if self._writer is None:
            return
        if self._writes.full():  # write-behind never blocks the reader
            with contextlib.suppress(asyncio.QueueEmpty):
                self._writes.get_nowait()
            book_writes_dropped_total.inc()
        self._writes.put_nowait(row)
        questdb_write_queue_depth.labels(table="orderbook").set(self._writes.qsize())

    # ---- frames -----------------------------------------------------------
    async def handle_frame(self, frame: str) -> None:
        try:
            ev = self._parse(frame)
        except ValueError:
            logger.warning("book frame rejected")
            return
        if ev is None or ev.symbol not in self._demand.desired():
            return
        self._touch(self._topic_for(ev.symbol, ev.depth))
        tb = await self._ensure(ev.symbol)
        await tb.on_event(ev)
        if tb.warming is None:
            self.sync()  # a completed tier swap retires the old topic

    async def invalidate(self, reason: str) -> None:
        for tb in list(self._books.values()):
            await tb.active.invalidate(reason)

    async def check_timeouts(self) -> int:
        """SNAPSHOT_TIMEOUT: re-request every snapshot pending too long."""
        n = 0
        for tb in list(self._books.values()):
            e = tb.active
            if e.check_timeout(self._timeout_us):
                n += 1
                await e.on_snapshot_timeout()
        return n

    async def drain_writes(self, max_batch: int = 500) -> int:
        batch = [await self._writes.get()]
        while len(batch) < max_batch and not self._writes.empty():
            batch.append(self._writes.get_nowait())
        questdb_write_queue_depth.labels(table="orderbook").set(self._writes.qsize())
        if self._writer is not None:
            try:
                deltas = [r for r in batch if isinstance(r, BookDeltaRow)]
                if deltas:
                    await self._writer.write_book_deltas(deltas)
                for r in batch:
                    if isinstance(r, BookSnapshotRow):
                        await self._writer.write_book_snapshot(r)
            except Exception:  # write-behind must never take ingest down
                logger.warning("book write-behind failed", rows=len(batch))
        return len(batch)

    async def _health_loop(self) -> None:
        while True:
            ev = await self._health.get()
            if isinstance(ev, FeedHealthEvent) and ev.state in ("resubscribing", "degraded"):
                await self.invalidate("reconnect")  # the socket re-sends snapshots

    async def _write_loop(self) -> None:
        while True:
            await self.drain_writes()

    async def _timeout_loop(self) -> None:
        while True:
            await asyncio.sleep(max(0.5, self._timeout_us / 4_000_000))
            await self.check_timeouts()

    async def start(self) -> None:
        self._tasks = [
            spawn(self._health_loop(), name="book-health"),
            spawn(self._write_loop(), name="book-write-behind"),
            spawn(self._timeout_loop(), name="book-snapshot-timeout"),
        ]

    async def stop(self) -> None:
        tasks, self._tasks = self._tasks, []
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for sym in list(self._books):
            self._drop(sym)
        self._bus.unsubscribe(self._health)


__all__ = ["BookStream", "BookView", "BookWriter", "HealthSupervisor"]
