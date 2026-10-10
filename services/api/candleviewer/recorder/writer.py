"""StreamWriter — raw recorded streams to QuestDB over ILP (E16-T03, 20-architecture.md §3.8).

Consumes normalised market events for symbols in the RecordingPolicy effective set (kept as a
plain `set[str]` updated from `RecorderSetChanged`, so the hot path never queries a statechart —
C-2.20) and writes `trades`, `orderbook_deltas`, `orderbook_snapshots`, `tickers` and
`liquidations` (21-database-schema.md §4).

One **lane** per stream: its own bounded in-memory queue, flush lock, WAL and flush task, so a
stalled stream never delays another. A lane flushes at `flush_rows` (10 000) rows or once its
oldest queued row is `flush_interval_s` (200 ms) old, by the injected clock; the writer owns the
cadence (the ILP sink's own thresholds are irrelevant: every batch ends with `sink.flush`).

Backpressure ladder (never silent):
1. bounded in-memory queue (`max_queue_rows` per lane);
2. bounded on-disk WAL (`recorder/wal.py`, shared `wal_max_bytes`, default 1 GiB) when the queue
   is full or the sink failed — the lane stays in *spill mode* until the WAL is replayed;
3. drop, with a coalesced `recording_gaps` row (`cause='backpressure_drop'`) per
   (symbol, stream) window, a `critical` system event per episode and a `recorder_wal_full` log.

Replay (startup, `recover()`, and retried every `replay_retry_s` while in spill mode) sorts the
WAL in `exch_ts` order and suppresses duplicates by `(symbol, stream, exch_ts, seq, sub)`; an
interrupted replay is restarted from the start of `replay.wal`, which QuestDB `DEDUP UPSERT KEYS`
makes idempotent. Rows a failed ILP flush left inside the sink may be resent too (at-least-once,
the `IlpWriter` contract item 5) — same dedup argument.
"""

from __future__ import annotations

import asyncio
import os
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal, Protocol

import structlog

from candleviewer.observability.health_probes import SystemEvent, SystemEventWriter
from candleviewer.recorder.metrics import (
    recorder_bytes_written_total,
    recorder_flush_duration_seconds,
    recorder_rows_total,
    recorder_spill_bytes,
    recorder_write_backlog_rows,
)
from candleviewer.recorder.models import RecorderSetChanged
from candleviewer.recorder.wal import SpillWal, WalBudget, WalRecord
from candleviewer.storage.questdb.ilp_writer import serialize_ilp_line
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS

Stream = Literal["trades", "orderbook_deltas", "orderbook_snapshots", "tickers", "liquidations"]
STREAMS: Final[tuple[Stream, ...]] = (
    "trades",
    "orderbook_deltas",
    "orderbook_snapshots",
    "tickers",
    "liquidations",
)
#: QuestDB table -> Postgres `stream_kind` (recording_gaps.stream).
STREAM_KIND: Final[dict[Stream, str]] = {
    "trades": "trades",
    "orderbook_deltas": "orderbook_delta",
    "orderbook_snapshots": "orderbook_snapshot",
    "tickers": "tickers",
    "liquidations": "liquidations",
}
GAP_CAUSE: Final = "backpressure_drop"
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]


# --- inputs (structural: M11 may not import exchange.base, CONSTITUTION §3) ------------------


class LevelLike(Protocol):
    @property
    def price(self) -> Decimal: ...
    @property
    def qty(self) -> Decimal: ...


class _Market(Protocol):
    @property
    def symbol(self) -> str: ...
    @property
    def ts_event(self) -> int: ...


class TradeLike(_Market, Protocol):
    @property
    def trade_id(self) -> str: ...
    @property
    def price(self) -> Decimal: ...
    @property
    def qty(self) -> Decimal: ...
    @property
    def notional(self) -> Decimal: ...
    @property
    def side(self) -> str: ...
    @property
    def is_block_trade(self) -> bool: ...
    @property
    def seq(self) -> int: ...


class BookSnapshotLike(_Market, Protocol):
    @property
    def depth(self) -> int: ...
    @property
    def bids(self) -> Sequence[LevelLike]: ...
    @property
    def asks(self) -> Sequence[LevelLike]: ...
    @property
    def update_id(self) -> int: ...
    @property
    def cross_seq(self) -> int: ...


class BookDeltaLike(BookSnapshotLike, Protocol):
    @property
    def prev_update_id(self) -> int: ...


class TickerLike(_Market, Protocol):
    @property
    def last_price(self) -> Decimal | None: ...
    @property
    def mark_price(self) -> Decimal | None: ...
    @property
    def index_price(self) -> Decimal | None: ...
    @property
    def bid1_price(self) -> Decimal | None: ...
    @property
    def bid1_qty(self) -> Decimal | None: ...
    @property
    def ask1_price(self) -> Decimal | None: ...
    @property
    def ask1_qty(self) -> Decimal | None: ...
    @property
    def open_interest(self) -> Decimal | None: ...
    @property
    def open_interest_value(self) -> Decimal | None: ...
    @property
    def turnover_24h(self) -> Decimal | None: ...
    @property
    def volume_24h(self) -> Decimal | None: ...
    @property
    def price_24h_pcnt(self) -> Decimal | None: ...
    @property
    def funding_rate(self) -> Decimal | None: ...
    @property
    def next_funding_time(self) -> int | None: ...


class LiquidationLike(_Market, Protocol):
    @property
    def price(self) -> Decimal: ...
    @property
    def qty(self) -> Decimal: ...
    @property
    def liquidated_side(self) -> str: ...
    @property
    def notional(self) -> Decimal: ...
    @property
    def batch_index(self) -> int: ...


# --- outputs -------------------------------------------------------------------------------


class RowSink(Protocol):
    """The ILP surface used (`storage.questdb.IlpWriter` conforms)."""

    async def write_rows(
        self, table: str, rows: list[dict[str, object]], ts_us_key: str
    ) -> None: ...

    async def flush(self, table: str | None = None) -> None: ...


class RecorderStore(Protocol):
    """Postgres side (`SqlAlchemyRecorderRepository` conforms): the symbol's live session."""

    async def add_session_counters(
        self,
        symbol: str,
        *,
        messages_received: int,
        messages_dropped: int,
        bytes_written: int,
        reconnect_count: int,
    ) -> bool: ...

    async def record_live_gap(
        self, *, symbol: str, stream: str, gap_start: datetime, gap_end: datetime, cause: str
    ) -> bool: ...


class RecorderWalVolumeError(RuntimeError):
    """SR-096 / threat S2: the WAL shares a volume with a path the backend needs."""

    code = "recorder_wal_volume_shared"


def check_wal_volume(wal_dir: Path, protected: Sequence[Path]) -> None:
    """Refuse to record when `wal_dir` lives on the same device as any `protected` path."""
    wal_dir.mkdir(parents=True, exist_ok=True)
    dev = os.stat(wal_dir).st_dev
    for path in protected:
        if path.exists() and os.stat(path).st_dev == dev:
            raise RecorderWalVolumeError(f"WAL dir shares a volume with {path.name!r}")


# --- event -> rows ---------------------------------------------------------------------------


def _num(value: Decimal) -> str:
    """Exact decimal text for an ILP DOUBLE field (never via `float`, never exponent form)."""
    return format(value, "f")


def _rec(
    stream: Stream, symbol: str, ts: int, seq: int, sub: int, row: dict[str, object]
) -> WalRecord:
    row["ts"] = ts
    row["symbol"] = symbol
    return WalRecord(stream=stream, symbol=symbol, exch_ts=ts, seq=seq, sub=sub, row=row)


def trade_records(ev: TradeLike) -> list[WalRecord]:
    row: dict[str, object] = {
        "side": ev.side,
        "price": _num(ev.price),
        "size": _num(ev.qty),
        "notional": _num(ev.notional),
        "trade_id": ev.trade_id,
        "is_block": ev.is_block_trade,
        "seq": ev.seq,
    }
    return [_rec("trades", ev.symbol, ev.ts_event, ev.seq, 0, row)]


def _levels(ev: BookSnapshotLike) -> list[tuple[str, LevelLike]]:
    return [("bid", lv) for lv in ev.bids] + [("ask", lv) for lv in ev.asks]


def delta_records(ev: BookDeltaLike) -> list[WalRecord]:
    out: list[WalRecord] = []
    for sub, (side, lv) in enumerate(_levels(ev)):
        row: dict[str, object] = {
            "depth": ev.depth,
            "side": side,
            "price": _num(lv.price),
            "size": _num(lv.qty),
            # Without book state an insert is indistinguishable from an update (E08 owns it).
            "action": "delete" if lv.qty == 0 else "update",
            "update_id": ev.update_id,
            "cross_seq": ev.cross_seq,
        }
        out.append(_rec("orderbook_deltas", ev.symbol, ev.ts_event, ev.update_id, sub, row))
    return out


def snapshot_records(ev: BookSnapshotLike) -> list[WalRecord]:
    import orjson

    row: dict[str, object] = {
        "depth": ev.depth,
        "update_id": ev.update_id,
        "cross_seq": ev.cross_seq,
        "source": "exchange",
        "bids": orjson.dumps([[_num(lv.price), _num(lv.qty)] for lv in ev.bids]).decode(),
        "asks": orjson.dumps([[_num(lv.price), _num(lv.qty)] for lv in ev.asks]).decode(),
        "level_count": len(ev.bids) + len(ev.asks),
    }
    return [_rec("orderbook_snapshots", ev.symbol, ev.ts_event, ev.update_id, 0, row)]


_TICKER_COLS: Final = (
    ("last_price", "last_price"),
    ("mark_price", "mark_price"),
    ("index_price", "index_price"),
    ("bid1_price", "bid1_price"),
    ("bid1_qty", "bid1_size"),
    ("ask1_price", "ask1_price"),
    ("ask1_qty", "ask1_size"),
    ("open_interest", "open_interest"),
    ("open_interest_value", "open_interest_value"),
    ("turnover_24h", "turnover_24h"),
    ("volume_24h", "volume_24h"),
    ("price_24h_pcnt", "price_24h_pcnt"),
    ("funding_rate", "funding_rate"),
)


def ticker_records(ev: TickerLike) -> list[WalRecord]:
    row: dict[str, object] = {}
    for attr, col in _TICKER_COLS:
        value: Decimal | None = getattr(ev, attr)
        if value is not None:
            row[col] = _num(value)
    if ev.next_funding_time is not None:
        row["next_funding_ts"] = ev.next_funding_time
    return [_rec("tickers", ev.symbol, ev.ts_event, 0, 0, row)]


def liquidation_records(ev: LiquidationLike) -> list[WalRecord]:
    # DDL `side` = the closing order's side: a long is closed by a sell (never read `side`).
    closing = "sell" if ev.liquidated_side == "long" else "buy"
    row: dict[str, object] = {
        "side": closing,
        "price": _num(ev.price),
        "size": _num(ev.qty),
        "notional": _num(ev.notional),
        "stream": "all",
    }
    return [_rec("liquidations", ev.symbol, ev.ts_event, ev.batch_index, 0, row)]


# --- the writer ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WriterConfig:
    """`CV_RECORDER_WAL_*` (20-architecture.md §7.2) and the §3.8 batching thresholds."""

    wal_dir: Path
    wal_max_bytes: int = 1 << 30
    flush_rows: int = 10_000
    flush_interval_s: float = 0.2
    #: Per-lane in-memory bound (rows); past it the lane spills (C-2.18).
    max_queue_rows: int = 50_000
    write_timeout_s: float = 5.0
    store_timeout_s: float = 5.0
    replay_retry_s: float = 1.0
    counters_interval_s: float = 10.0
    poll_s: float = 0.01


@dataclass(slots=True)
class _Counters:
    received: int = 0
    dropped: int = 0
    bytes_written: int = 0
    reconnects: int = 0

    def any(self) -> bool:
        return bool(self.received or self.dropped or self.bytes_written or self.reconnects)


@dataclass(slots=True)
class _Lane:
    stream: Stream
    wal: SpillWal
    queue: deque[WalRecord] = field(default_factory=deque)
    oldest_at: float | None = None
    spilling: bool = False
    next_replay_at: float = 0.0
    flush_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    wal_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class StreamWriter:
    """Per-stream batched ILP writer with WAL spill and explicit drop gaps (module docstring)."""

    def __init__(
        self,
        sink: RowSink,
        store: RecorderStore,
        events: SystemEventWriter,
        config: WriterConfig,
        *,
        clock: Callable[[], float],
        wall_clock_us: Callable[[], int],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._sink = sink
        self._store = store
        self._events = events
        self._cfg = config
        self._clock = clock
        self._wall_us = wall_clock_us
        self._sleep = sleep
        self._budget = WalBudget(config.wal_max_bytes)
        self._lanes: dict[Stream, _Lane] = {
            s: _Lane(stream=s, wal=SpillWal(config.wal_dir / s, self._budget)) for s in STREAMS
        }
        self._active: set[str] = set()
        self._counters: dict[str, _Counters] = {}
        #: (symbol, stream) -> [first, last] dropped exch_ts (µs), not yet persisted.
        self._gaps: dict[tuple[str, Stream], list[int]] = {}
        #: Last observed delta update_id per symbol (seq jumps are E16-T04's to convert).
        self._last_update_id: dict[str, int] = {}
        self.seq_jumps: deque[tuple[str, int, int]] = deque(maxlen=1024)
        self._tasks: set[asyncio.Task[None]] = set()
        self._next_counters_at = 0.0
        self._publish_gauges()

    # -- effective set (C-2.20: a plain set, never an interpreter) ---------------------------

    def seed(self, symbols: Sequence[str]) -> None:
        self._active = set(symbols)

    def on_set_changed(self, event: RecorderSetChanged) -> None:
        if event.change == "removed":
            self._active.discard(event.symbol)
        else:
            self._active.add(event.symbol)

    def is_recording(self, symbol: str) -> bool:
        return symbol in self._active

    def note_reconnect(self, symbol: str) -> None:
        self._ctr(symbol).reconnects += 1

    # -- hot path ------------------------------------------------------------------------------

    async def on_trade(self, ev: TradeLike) -> None:
        if ev.symbol in self._active:
            await self._admit("trades", ev.symbol, trade_records(ev))

    async def on_book_delta(self, ev: BookDeltaLike) -> None:
        if ev.symbol not in self._active:
            return
        last = self._last_update_id.get(ev.symbol)
        if last is not None and ev.prev_update_id != last:
            self.seq_jumps.append((ev.symbol, last, ev.prev_update_id))
        self._last_update_id[ev.symbol] = ev.update_id
        await self._admit("orderbook_deltas", ev.symbol, delta_records(ev))

    async def on_book_snapshot(self, ev: BookSnapshotLike) -> None:
        if ev.symbol in self._active:
            self._last_update_id[ev.symbol] = ev.update_id
            await self._admit("orderbook_snapshots", ev.symbol, snapshot_records(ev))

    async def on_ticker(self, ev: TickerLike) -> None:
        if ev.symbol in self._active:
            await self._admit("tickers", ev.symbol, ticker_records(ev))

    async def on_liquidation(self, ev: LiquidationLike) -> None:
        if ev.symbol in self._active:
            await self._admit("liquidations", ev.symbol, liquidation_records(ev))

    def _ctr(self, symbol: str) -> _Counters:
        ctr = self._counters.get(symbol)
        if ctr is None:
            ctr = self._counters[symbol] = _Counters()
        return ctr

    async def _admit(self, stream: Stream, symbol: str, records: list[WalRecord]) -> None:
        self._ctr(symbol).received += 1
        if not records:
            return
        lane = self._lanes[stream]
        if lane.spilling or len(lane.queue) + len(records) > self._cfg.max_queue_rows:
            await self._spill(lane, records)
            return
        if not lane.queue:
            lane.oldest_at = self._clock()
        lane.queue.extend(records)
        self._publish_gauges()

    # -- flush ---------------------------------------------------------------------------------

    def _due(self, lane: _Lane, now: float) -> bool:
        if not lane.queue or lane.oldest_at is None:
            return False
        full = len(lane.queue) >= self._cfg.flush_rows
        return full or now - lane.oldest_at >= self._cfg.flush_interval_s

    async def pump(self, stream: Stream) -> None:
        """One lane step: replay the WAL if due, else flush the batch if due."""
        lane = self._lanes[stream]
        now = self._clock()
        if lane.spilling:
            if now >= lane.next_replay_at:
                await self._replay(lane)
        elif self._due(lane, now):
            await self._flush(lane)

    async def _write(self, stream: Stream, records: Sequence[WalRecord]) -> None:
        """Send one batch and flush it through the sink, bounded by `write_timeout_s`."""
        rows = [dict(r.row) for r in records]
        started = self._clock()
        async with asyncio.timeout(self._cfg.write_timeout_s):
            await self._sink.write_rows(stream, rows, "ts")
            await self._sink.flush(stream)
        recorder_flush_duration_seconds.observe(max(self._clock() - started, 0.0))
        recorder_rows_total.labels(stream=stream).inc(len(records))
        schema = ALL_SCHEMAS[stream]
        per_symbol: dict[str, int] = {}
        for r in records:
            body = {k: v for k, v in r.row.items() if k != "ts"}
            size = len(serialize_ilp_line(schema, body, r.exch_ts)) + 1
            per_symbol[r.symbol] = per_symbol.get(r.symbol, 0) + size
        for symbol, size in per_symbol.items():
            self._ctr(symbol).bytes_written += size
            recorder_bytes_written_total.labels(symbol=symbol, stream=stream).inc(size)

    async def _flush(self, lane: _Lane) -> None:
        async with lane.flush_lock:
            if lane.spilling or not lane.queue:
                return
            n = min(len(lane.queue), self._cfg.flush_rows)
            batch = [lane.queue.popleft() for _ in range(n)]
            lane.oldest_at = self._clock() if lane.queue else None
            try:
                await self._write(lane.stream, batch)
            except asyncio.CancelledError:
                lane.queue.extendleft(reversed(batch))
                raise
            except Exception as exc:
                logger().error(
                    "recorder_write_failed", stream=lane.stream, rows=len(batch), error=str(exc)
                )
                rest = list(lane.queue)
                lane.queue.clear()
                lane.oldest_at = None
                await self._spill(lane, batch + rest)
            finally:
                self._publish_gauges()

    # -- spill / drop --------------------------------------------------------------------------

    async def _spill(self, lane: _Lane, records: list[WalRecord]) -> None:
        async with lane.wal_lock:
            # Set under the WAL lock so a concurrent replay never strands spilled rows.
            if not lane.spilling:
                lane.spilling = True
                lane.next_replay_at = self._clock() + self._cfg.replay_retry_s
                # Queued rows are older than `records`: they go to the WAL first.
                records = [*lane.queue, *records]
                lane.queue.clear()
                lane.oldest_at = None
                logger().warning("recorder_spill_started", stream=lane.stream)
            try:
                written = await asyncio.to_thread(lane.wal.append, records)
            except OSError as exc:  # disk full / I/O error: chaos scenario 13
                logger().error("recorder_wal_full", stream=lane.stream, error=str(exc))
                written = 0
        if written < len(records):
            await self._drop(lane.stream, records[written:])
        self._publish_gauges()

    async def _drop(self, stream: Stream, records: list[WalRecord]) -> None:
        new_episodes: set[str] = set()
        for rec in records:
            self._ctr(rec.symbol).dropped += 1
            window = self._gaps.get((rec.symbol, stream))
            if window is None:
                self._gaps[(rec.symbol, stream)] = [rec.exch_ts, rec.exch_ts]
                new_episodes.add(rec.symbol)
            else:
                window[0] = min(window[0], rec.exch_ts)
                window[1] = max(window[1], rec.exch_ts)
        for symbol in sorted(new_episodes):
            logger().critical("recorder_wal_full", symbol=symbol, stream=stream)
            event = SystemEvent(
                component="recorder",
                kind="recorder_wal_full",
                severity="critical",
                message=f"recorder dropping {stream} for {symbol}: WAL full, QuestDB unavailable",
                details={"symbol": symbol, "stream": stream, "cause": GAP_CAUSE},
            )
            try:
                async with asyncio.timeout(self._cfg.store_timeout_s):
                    await self._events.write(event)
            except Exception as exc:
                logger().error("recorder_event_write_failed", symbol=symbol, error=str(exc))

    # -- replay --------------------------------------------------------------------------------

    async def recover(self) -> None:
        """QuestDB is back (readiness probe): replay every spilling lane now."""
        for lane in self._lanes.values():
            if lane.spilling:
                lane.next_replay_at = 0.0
                await self._replay(lane)

    async def _replay(self, lane: _Lane) -> bool:
        """Drain the lane's WAL into QuestDB in `exch_ts` order. True once fully drained."""
        async with lane.flush_lock:
            while True:
                async with lane.wal_lock:
                    pending = await asyncio.to_thread(lane.wal.begin_replay)
                    if not pending:
                        lane.spilling = False
                        logger().info("recorder_spill_drained", stream=lane.stream)
                        self._publish_gauges()
                        return True
                    result = await asyncio.to_thread(lane.wal.read_replay)
                if result.corrupt_bytes:
                    logger().error(
                        "recorder_wal_corrupt", stream=lane.stream, bytes=result.corrupt_bytes
                    )
                    self._corrupt_gap(lane.stream, result.records)
                ordered = dedup_sorted(result.records)
                try:
                    for i in range(0, len(ordered), self._cfg.flush_rows):
                        await self._write(lane.stream, ordered[i : i + self._cfg.flush_rows])
                except Exception as exc:
                    # `replay.wal` stays; the whole file is retried later (dedup keys).
                    lane.next_replay_at = self._clock() + self._cfg.replay_retry_s
                    logger().warning("recorder_replay_failed", stream=lane.stream, error=str(exc))
                    return False
                async with lane.wal_lock:
                    await asyncio.to_thread(lane.wal.finish_replay)
                self._publish_gauges()

    def _corrupt_gap(self, stream: Stream, good: list[WalRecord]) -> None:
        """A corrupt WAL tail is a loss of unknown extent: gap from the last good row to now."""
        now = self._wall_us()
        start = max((r.exch_ts for r in good), default=now - 1)
        for symbol in sorted({r.symbol for r in good}) or sorted(self._active):
            window = self._gaps.setdefault((symbol, stream), [start, start])
            window[1] = max(window[1], now)

    # -- periodic: gaps + counters -------------------------------------------------------------

    async def flush_gaps(self) -> None:
        for (symbol, stream), (first, last) in list(self._gaps.items()):
            gap_start = _EPOCH + timedelta(microseconds=first)
            gap_end = _EPOCH + timedelta(microseconds=max(last, first + 1))
            try:
                async with asyncio.timeout(self._cfg.store_timeout_s):
                    ok = await self._store.record_live_gap(
                        symbol=symbol,
                        stream=STREAM_KIND[stream],
                        gap_start=gap_start,
                        gap_end=gap_end,
                        cause=GAP_CAUSE,
                    )
            except Exception as exc:
                logger().error("recorder_gap_write_failed", symbol=symbol, error=str(exc))
                continue
            if not ok:
                logger().error("recorder_gap_no_session", symbol=symbol, stream=stream)
            # Only a window untouched since the snapshot is removed (no lost extension).
            if self._gaps.get((symbol, stream)) == [first, last]:
                del self._gaps[(symbol, stream)]

    async def flush_counters(self) -> None:
        for symbol, ctr in list(self._counters.items()):
            if not ctr.any():
                continue
            snap = _Counters(ctr.received, ctr.dropped, ctr.bytes_written, ctr.reconnects)
            try:
                async with asyncio.timeout(self._cfg.store_timeout_s):
                    await self._store.add_session_counters(
                        symbol,
                        messages_received=snap.received,
                        messages_dropped=snap.dropped,
                        bytes_written=snap.bytes_written,
                        reconnect_count=snap.reconnects,
                    )
            except Exception as exc:
                logger().error("recorder_counters_write_failed", symbol=symbol, error=str(exc))
                continue
            ctr.received -= snap.received
            ctr.dropped -= snap.dropped
            ctr.bytes_written -= snap.bytes_written
            ctr.reconnects -= snap.reconnects

    async def tick(self) -> None:
        """Every `counters_interval_s`: persist gap rows, then the per-symbol counters."""
        now = self._clock()
        if now < self._next_counters_at:
            return
        self._next_counters_at = now + self._cfg.counters_interval_s
        await self.flush_gaps()
        await self.flush_counters()

    # -- lifecycle -----------------------------------------------------------------------------

    async def start(self) -> None:
        """Replay any WAL a previous process left (startup recovery), then run the lanes."""
        self._next_counters_at = self._clock() + self._cfg.counters_interval_s
        for lane in self._lanes.values():
            if lane.wal.has_data():
                lane.spilling = True
                await self._replay(lane)
        for stream in STREAMS:
            self._spawn(self._lane_loop(stream), f"recorder-lane-{stream}")
        self._spawn(self._tick_loop(), "recorder-counters")

    def _spawn(self, coro: Coroutine[object, object, None], name: str) -> None:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger().error(
                "recorder_task_crashed", task=task.get_name(), error=str(task.exception())
            )

    async def _lane_loop(self, stream: Stream) -> None:
        while True:
            try:
                await self.pump(stream)
            except Exception as exc:
                logger().error("recorder_lane_error", stream=stream, error=str(exc))
            await self._sleep(self._cfg.poll_s)

    async def _tick_loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:
                logger().error("recorder_tick_error", error=str(exc))
            await self._sleep(self._cfg.poll_s * 10)

    async def stop(self, timeout_s: float = 10.0) -> None:
        """Cancel the loops, flush what is queued (spilling on failure), persist gaps/counters."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            async with asyncio.timeout(timeout_s):
                for lane in self._lanes.values():
                    while lane.queue and not lane.spilling:
                        await self._flush(lane)
        except TimeoutError:
            for lane in self._lanes.values():
                if lane.queue:
                    await self._spill(lane, [])
        self._next_counters_at = 0.0
        await self.tick()

    # -- observability -------------------------------------------------------------------------

    @property
    def backlog_rows(self) -> int:
        return sum(len(lane.queue) for lane in self._lanes.values())

    @property
    def spill_bytes(self) -> int:
        return self._budget.used

    def is_spilling(self, stream: Stream) -> bool:
        return self._lanes[stream].spilling

    def pending_gaps(self) -> dict[tuple[str, Stream], tuple[int, int]]:
        return {k: (v[0], v[1]) for k, v in self._gaps.items()}

    def _publish_gauges(self) -> None:
        recorder_write_backlog_rows.set(self.backlog_rows)
        recorder_spill_bytes.set(self._budget.used)


def dedup_sorted(records: Sequence[WalRecord]) -> list[WalRecord]:
    """`exch_ts` order (stable), first occurrence of each `(symbol, stream, exch_ts, seq, sub)`."""
    seen: set[tuple[str, str, int, int, int]] = set()
    out: list[WalRecord] = []
    for rec in sorted(records, key=lambda r: r.exch_ts):
        if rec.key not in seen:
            seen.add(rec.key)
            out.append(rec)
    return out
