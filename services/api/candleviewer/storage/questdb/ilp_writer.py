"""ILP-over-TCP batched writer for the QuestDB hot tier (E07-T03).

`docs/plan/21-database-schema.md` Sec.4.14: batched 5 000 rows or 100 ms,
per-table buffers, bounded queue with explicit backpressure (never silently
drop — trades/executions must never be dropped, `20-architecture.md` Sec.3.1),
reconnect with exponential backoff and bounded jitter, `flush()` awaited on
`stop()`.

Line format: `table,tag=val,... field=val,... timestamp_ns` — `SYMBOL`
columns are ILP *tags*, everything else (`DOUBLE`, `LONG`, `STRING`,
`BOOLEAN`, `TIMESTAMP`) is an ILP *field*. Getting a `SYMBOL` column emitted
as a field (or vice versa) silently changes the storage shape (dictionary
encoding vs not), so `TableSchema` below is the single source of which
columns are tags — never inferred per-row.

IlpWriter contract (E49-K01-F2, #1856 — the storage-writer defect cluster
#1835/#1636/#1701 kept recurring because these semantics were implicit):

1. **Bounded queue, overflow = block-and-self-flush, never drop (C-2.18).**
   Admission is all-or-nothing per batch. If the batch does not fit, the
   caller flushes the queue itself (outside the lock) and pays the sink's
   drain time — that is the backpressure; `queue_full_total` counts it. An
   empty queue always admits, so a batch larger than `max_queue_rows`
   completes (the queue may exceed the cap by at most one batch).
2. **Validation before enqueue.** Every row of a batch is validated before
   any row is buffered; a malformed row raises an `IlpRowError` subclass
   (`MissingDesignatedTimestamp`, `InvalidSymbol`, `UnknownIlpTable`) and the
   whole batch is rejected untouched, so a bad row never poisons a batch.
3. **Readiness.** `is_ready` is True only while connected (readiness probe
   passed) and not closed; `await ready(timeout_s)` waits for it or raises
   `StorageTierUnavailable`.
4. **Acknowledgement.** A row is *acknowledged* once `write_rows` returns
   (or once it has been admitted, if a later flush in the same call raised).
   Acknowledged rows leave the buffer only after a successful transport
   write; a failed **or cancelled** flush requeues them at the head, marks
   the writer disconnected and closes the transport, so the next flush
   reconnects on a clean line boundary (a cancelled write may have left a
   torn ILP line on the old socket) and resends the whole batch.
5. **At-least-once, not exactly-once.** A retry after a failed/cancelled
   flush may resend rows whose bytes already left. This is safe only
   because every QuestDB table declares `DEDUP UPSERT KEYS`
   (`21-database-schema.md` Sec.4.14; asserted for every registered table
   in `ALL_SCHEMAS` by the contract suite). `rows_written_total` is not
   incremented for such bytes, so `reconcile()` can briefly report a
   negative gap after a resend.
6. **Ordering is per flush only.** Rows are never lost or admitted twice,
   but concurrent self-flushes of one table take disjoint slices and send
   outside the lock, so batches may reach the sink out of order, and a
   failed flush is requeued behind rows admitted since. QuestDB `o3MaxLag`
   plus dedup absorbs this.
7. **Close.** `stop(timeout_s)` drains, then closes the transport. The
   default drain is bounded (`DEFAULT_STOP_TIMEOUT_S`, 30 s) because
   reconnect retries forever while QuestDB is down. On timeout/failure it
   raises `StorageTierUnavailable` naming the buffered-row count; those rows
   stay in the (closed) writer and are the **caller's** to spill/log — there
   is no handoff API yet (wiring ticket). After `stop()` `write_rows`
   raises `StorageTierUnavailable`.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

import structlog

from candleviewer.storage.errors import (
    InvalidSymbol,
    MissingDesignatedTimestamp,
    StorageTierUnavailable,
    UnknownIlpTable,
)

logger = structlog.get_logger(__name__)

DEFAULT_STOP_TIMEOUT_S = 30.0
_FLUSH_ROWS = 5_000
_FLUSH_INTERVAL_S = 0.1  # 100 ms, per Sec.4.14
_RECONNECT_BASE_S = 0.5
_RECONNECT_MAX_S = 30.0
_JITTER_LOW = 0.5
_JITTER_HIGH = 1.5


class IlpTransport(Protocol):
    """The minimal socket surface the writer needs — a `Protocol` so tests
    supply an in-memory fake instead of a real TCP connection."""

    async def connect(self) -> None: ...

    async def write(self, data: bytes) -> None: ...

    async def close(self) -> None: ...


def _escape_symbol(value: str) -> str:
    """Escape a `SYMBOL`/tag value per ILP: backslash, space, comma and `=`
    are escaped with a backslash. A raw newline or carriage-return would
    terminate (or corrupt) the ILP line, so those are also backslash-encoded
    rather than rejected, keeping every buffered row exactly one line even
    for hostile/unexpected input (defence in depth beyond the closed-enum
    tag values normally seen here)."""
    return (
        value.replace("\\", "\\\\")
        .replace(" ", r"\ ")
        .replace(",", r"\,")
        .replace("=", r"\=")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def _escape_string_field(value: str) -> str:
    """Escape a `STRING` field value: backslash and double-quote, plus a raw
    newline/carriage-return (which would otherwise terminate/corrupt the ILP
    line) encoded as the two-character escape sequence."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")


@dataclass(frozen=True, slots=True)
class TableSchema:
    """Which columns of one table are ILP tags (`SYMBOL`) vs fields, and
    which field (if any) is a `STRING` needing quote/escape handling."""

    name: str
    tag_columns: tuple[str, ...]
    string_field_columns: tuple[str, ...] = ()
    boolean_field_columns: tuple[str, ...] = ()
    timestamp_field_columns: tuple[str, ...] = ()


def serialize_ilp_line(schema: TableSchema, row: dict[str, object], ts_us: int) -> str:
    """Serialize one row dict into a single ILP line for `schema.name`.

    `row` must not include the designated timestamp column — `ts_us` is
    always appended as the line's own timestamp (integer microseconds,
    matching every hot-tier client and the read Protocols, per
    `docs/plan/21-database-schema.md` Sec.4 conventions).
    """
    tags: list[str] = []
    for col in schema.tag_columns:
        value = row.get(col)
        if value is None:
            continue
        tags.append(f"{col}={_escape_symbol(str(value))}")

    fields: list[str] = []
    for col, value in row.items():
        if col in schema.tag_columns:
            continue
        if value is None:
            continue
        if col in schema.string_field_columns:
            fields.append(f'{col}="{_escape_string_field(str(value))}"')
        elif col in schema.boolean_field_columns:
            fields.append(f"{col}={'true' if value else 'false'}")
        elif col in schema.timestamp_field_columns:
            # QuestDB ILP: timestamp fields are microseconds suffixed with `t`.
            fields.append(f"{col}={int(str(value))}t")
        elif isinstance(value, int) and not isinstance(value, bool):
            fields.append(f"{col}={value}i")
        else:
            fields.append(f"{col}={value}")

    tag_part = "," + ",".join(tags) if tags else ""
    field_part = ",".join(fields)
    ts_ns = ts_us * 1_000
    return f"{schema.name}{tag_part} {field_part} {ts_ns}"


@dataclass
class _TableBuffer:
    schema: TableSchema
    last_flush: float
    rows: list[tuple[dict[str, object], int]] = field(default_factory=list)


def _designated_ts_us(row: dict[str, object], ts_us_key: str, index: int) -> int:
    """Return the row's designated timestamp (µs) or raise `MissingDesignatedTimestamp`.

    Never falls back to "now": a row without event time is malformed."""
    if ts_us_key not in row:
        raise MissingDesignatedTimestamp(f"row {index} lacks designated timestamp {ts_us_key!r}")
    raw = row[ts_us_key]
    if isinstance(raw, bool):
        raise MissingDesignatedTimestamp(f"row {index}: {ts_us_key!r} is a bool")
    try:
        ts_us = int(str(raw))
    except ValueError as exc:
        raise MissingDesignatedTimestamp(f"row {index}: {ts_us_key!r} is not an integer") from exc
    if ts_us < 0:
        raise MissingDesignatedTimestamp(f"row {index}: {ts_us_key!r} is negative")
    return ts_us


def _check_symbol(schema: TableSchema, row: dict[str, object], index: int) -> None:
    if "symbol" not in schema.tag_columns:
        return
    sym = row.get("symbol")
    if not isinstance(sym, str) or not sym.strip():
        raise InvalidSymbol(f"row {index}: symbol must be a non-empty string")


class IlpWriter:
    """Batched ILP writer: one queue/buffer per table, flush at 5 000 rows
    or 100 ms (whichever first), bounded queue with explicit backpressure.

    Backpressure policy: the internal queue is bounded
    (`max_queue_rows`); when full, `write_rows` **awaits** a flush it
    performs itself (never drops) so a slow/down QuestDB backs the caller up
    rather than silently losing trades. `stop()` awaits a final `flush()`.
    """

    def __init__(
        self,
        transport: IlpTransport,
        schemas: dict[str, TableSchema],
        *,
        max_queue_rows: int = 200_000,
        flush_rows: int = _FLUSH_ROWS,
        flush_interval_s: float = _FLUSH_INTERVAL_S,
        rng: random.Random | None = None,
        readiness_probe: Callable[[], Awaitable[bool]] | None = None,
        committed_counter: Callable[[], Awaitable[int]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_queue_rows < 1:
            raise ValueError("max_queue_rows must be >= 1")
        # Injected monotonic clock (seconds) for the 100 ms flush window, so
        # the contract suite drives time deterministically (no sleeps).
        self._clock = clock
        self._closed = False
        self._ready_event = asyncio.Event()
        self._queue_full_total = 0
        # Optional: returns total rows QuestDB has committed (e.g. via PG-wire
        # count()). MUST be cumulative/monotonic (e.g. count() of the tables):
        # baselined once at first successful connect and deliberately NOT
        # re-baselined on reconnect, so rows lost across a reconnect still
        # show as a gap. `reconcile()` reports sent-vs-committed (#1701).
        self._committed_counter = committed_counter
        self._committed_baseline: int | None = None
        # ILP/TCP has no acks and the port can accept before the ILP listener
        # is live, so a batch sent then vanishes. When set, the probe (e.g.
        # `SELECT 1` over PG-wire / HTTP /exec) must return True after every
        # (re)connect before any write; buffered rows are held meanwhile.
        self._readiness_probe = readiness_probe
        self._transport = transport
        self._schemas = schemas
        self._max_queue_rows = max_queue_rows
        self._flush_rows = flush_rows
        self._flush_interval_s = flush_interval_s
        self._rng = rng if rng is not None else random.Random()  # noqa: S311 - jitter, not crypto
        self._buffers: dict[str, _TableBuffer] = {}
        self._total_buffered = 0
        self._connected = False
        self._reconnect_delay_s = _RECONNECT_BASE_S
        self._write_errors_total = 0
        self._rows_written_total = 0
        self._unreconciled_rows = 0
        self._lock = asyncio.Lock()

    @property
    def rows_written_total(self) -> int:
        return self._rows_written_total

    @property
    def write_errors_total(self) -> int:
        return self._write_errors_total

    @property
    def queue_full_total(self) -> int:
        """Times a batch did not fit and the caller had to self-flush (backpressure)."""
        return self._queue_full_total

    @property
    def total_buffered(self) -> int:
        """Acknowledged rows not yet written to the transport, across all tables."""
        return self._total_buffered

    @property
    def is_ready(self) -> bool:
        """Connected (readiness probe passed) and not closed."""
        return self._connected and not self._closed

    async def ready(self, timeout_s: float) -> None:
        """Wait until `is_ready`, or raise `StorageTierUnavailable` after `timeout_s`."""
        if self._closed:
            raise StorageTierUnavailable("questdb ILP writer is closed")
        try:
            async with asyncio.timeout(timeout_s):
                await self._ready_event.wait()
        except TimeoutError as exc:
            raise StorageTierUnavailable("questdb ILP writer not ready") from exc

    def _set_connected(self, value: bool) -> None:
        self._connected = value
        if value:
            self._ready_event.set()
        else:
            self._ready_event.clear()

    async def reconcile(self) -> int:
        """Rows sent since start minus rows QuestDB reports committed since
        start (0 = all landed; >0 = silently dropped/not yet visible). Logs a
        warning on a positive gap. Requires `committed_counter`."""
        if self._committed_counter is None or self._committed_baseline is None:
            raise RuntimeError("reconcile requires committed_counter and a started writer")
        committed = await self._committed_counter() - self._committed_baseline
        gap = self._rows_written_total - committed
        self._unreconciled_rows = max(gap, 0)
        if gap > 0:
            logger.warning(
                "questdb_ilp_sent_vs_committed_gap",
                sent=self._rows_written_total,
                committed=committed,
                gap=gap,
            )
        return gap

    @property
    def unreconciled_rows(self) -> int:
        return self._unreconciled_rows

    def queue_depth(self, table: str) -> int:
        buf = self._buffers.get(table)
        return len(buf.rows) if buf else 0

    async def start(self) -> None:
        await self._connect_with_backoff()

    async def _connect_with_backoff(self) -> None:
        while True:
            try:
                await self._transport.connect()
                if self._readiness_probe is not None and not await self._readiness_probe():
                    await self._transport.close()
                    raise ConnectionError("questdb not ready (readiness probe failed)")
                if self._committed_counter is not None and self._committed_baseline is None:
                    self._committed_baseline = await self._committed_counter()
                self._set_connected(True)
                self._reconnect_delay_s = _RECONNECT_BASE_S
                return
            except Exception as exc:
                self._write_errors_total += 1
                jittered_delay_s = self._jittered_delay_s()
                logger.warning(
                    "questdb_ilp_connect_failed",
                    error=str(exc),
                    retry_in_s=jittered_delay_s,
                )
                await asyncio.sleep(jittered_delay_s)
                self._reconnect_delay_s = min(self._reconnect_delay_s * 2, _RECONNECT_MAX_S)

    def _jittered_delay_s(self) -> float:
        """Bounded jitter on the current exponential-backoff delay: the
        base delay is multiplied by a factor drawn uniformly from
        `[_JITTER_LOW, _JITTER_HIGH]` and capped at `_RECONNECT_MAX_S`, so
        many reconnecting clients do not retry in lockstep (thundering herd)
        while the delay still grows exponentially and stays bounded."""
        factor = self._rng.uniform(_JITTER_LOW, _JITTER_HIGH)
        return min(self._reconnect_delay_s * factor, _RECONNECT_MAX_S)

    def _validate_batch(
        self, table: str, rows: list[dict[str, object]], ts_us_key: str
    ) -> tuple[TableSchema, list[tuple[dict[str, object], int]]]:
        """Validate every row and build the buffered entries — no side effects.

        Raises an `IlpRowError` subclass on the first bad row, so nothing of
        the batch is enqueued (contract item 2, #1636)."""
        schema = self._schemas.get(table)
        if schema is None:
            raise UnknownIlpTable(f"no TableSchema registered for table {table!r}")
        entries: list[tuple[dict[str, object], int]] = []
        for index, row in enumerate(rows):
            ts_us = _designated_ts_us(row, ts_us_key, index)
            _check_symbol(schema, row, index)
            # The designated timestamp travels only as the line's trailing
            # timestamp; also emitting it as a `ts=<n>i` field overrides it
            # with a LONG QuestDB reads at the wrong precision (#1630).
            entries.append(({k: v for k, v in row.items() if k != ts_us_key}, ts_us))
        return schema, entries

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        """Validate, then buffer `rows` for `table` (all-or-nothing), applying
        block-and-self-flush backpressure when the bounded queue is full;
        then flush `table` if its threshold (rows or interval) is met.

        Raises `IlpRowError` (nothing enqueued) for a malformed row and
        `StorageTierUnavailable` after `stop()` or on a failed flush (rows
        already admitted stay buffered — never dropped).

        When full, the caller flushes *outside* the lock — `flush()` needs
        the same lock to take a buffer, so flushing while holding it would
        deadlock the writer against its own flush path (#1835).
        """
        schema, entries = self._validate_batch(table, rows, ts_us_key)
        if not entries:
            return
        while True:
            if self._closed:
                raise StorageTierUnavailable("questdb ILP writer is closed")
            async with self._lock:
                # An empty queue always admits (a batch larger than the whole
                # budget would otherwise wait forever).
                if (
                    self._total_buffered == 0
                    or self._total_buffered + len(entries) <= self._max_queue_rows
                ):
                    buf = self._buffers.get(table)
                    if buf is None:
                        buf = _TableBuffer(schema=schema, last_flush=self._clock())
                        self._buffers[table] = buf
                    buf.rows.extend(entries)
                    self._total_buffered += len(entries)
                    break
                self._queue_full_total += 1
            # Queue full: the caller drains it itself (outside the lock) and
            # pays the transport's drain time — that *is* the backpressure.
            await self.flush(None)
        await self._maybe_flush(table)

    async def _maybe_flush(self, table: str) -> None:
        buf = self._buffers[table]
        elapsed = self._clock() - buf.last_flush
        if len(buf.rows) >= self._flush_rows or elapsed >= self._flush_interval_s:
            await self.flush(table)

    async def flush(self, table: str | None = None) -> None:
        """Flush one table's buffer (or every table's, if `table` is `None`).

        Rows leave the buffer only after a successful transport write; on a
        transport error **or cancellation** they are requeued at the head, so
        acknowledged rows are never lost (contract item 4)."""
        tables = [table] if table is not None else list(self._buffers.keys())
        for name in tables:
            buf = self._buffers.get(name)
            if buf is None or not buf.rows:
                continue
            async with self._lock:
                rows_to_send = buf.rows
                buf.rows = []
                self._total_buffered -= len(rows_to_send)
            try:
                lines = [serialize_ilp_line(buf.schema, row, ts_us) for row, ts_us in rows_to_send]
                payload = ("\n".join(lines) + "\n").encode("utf-8")
                if not self._connected:
                    await self._connect_with_backoff()
                await self._transport.write(payload)
            except BaseException as exc:
                # Requeue synchronously (no await) so it also runs on
                # cancellation; the lock is not needed — no await between
                # read and write of the buffer here.
                buf.rows = rows_to_send + buf.rows
                self._total_buffered += len(rows_to_send)
                # The write may be half-sent: drop the connection so the
                # next flush reconnects on a clean line boundary.
                self._set_connected(False)
                await self._close_transport_quietly()
                if not isinstance(exc, Exception):
                    raise  # CancelledError etc.: never swallowed
                self._write_errors_total += 1
                logger.error("questdb_ilp_write_failed", table=name, error=str(exc))
                raise StorageTierUnavailable(f"questdb ILP write failed for {name!r}") from exc
            self._rows_written_total += len(rows_to_send)
            buf.last_flush = self._clock()

    async def _close_transport_quietly(self) -> None:
        try:
            await self._transport.close()
        except Exception as exc:
            logger.warning("questdb_ilp_close_failed", error=str(exc))

    async def stop(self, timeout_s: float | None = DEFAULT_STOP_TIMEOUT_S) -> None:
        """Close: refuse new writes, drain every buffered row (bounded by
        `timeout_s`, default 30 s; `None` = unbounded), then close the
        transport. Idempotent.

        On a drain failure/timeout raises `StorageTierUnavailable` with the
        buffered-row count; those rows remain buffered (`total_buffered`) and
        are the caller's to spill/log."""
        self._closed = True
        try:
            async with asyncio.timeout(timeout_s):
                await self.flush(None)
        except (TimeoutError, StorageTierUnavailable) as exc:
            logger.error("questdb_ilp_drain_failed", buffered=self._total_buffered)
            raise StorageTierUnavailable(
                f"questdb ILP drain failed on stop; {self._total_buffered} rows "
                "remain buffered and are the caller's to spill/log"
            ) from exc
        finally:
            await self._transport.close()
            self._set_connected(False)
