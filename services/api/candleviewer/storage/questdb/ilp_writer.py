"""ILP-over-TCP batched writer for the QuestDB hot tier (E07-T03).

`docs/plan/21-database-schema.md` Sec.4.14: batched 5 000 rows or 100 ms,
per-table buffers, bounded queue with explicit backpressure (never silently
drop — trades/executions must never be dropped, `20-architecture.md` Sec.3.1),
reconnect with exponential backoff, `flush()` awaited on `stop()`.

Line format: `table,tag=val,... field=val,... timestamp_ns` — `SYMBOL`
columns are ILP *tags*, everything else (`DOUBLE`, `LONG`, `STRING`,
`BOOLEAN`, `TIMESTAMP`) is an ILP *field*. Getting a `SYMBOL` column emitted
as a field (or vice versa) silently changes the storage shape (dictionary
encoding vs not), so `TableSchema` below is the single source of which
columns are tags — never inferred per-row.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Protocol

import structlog

from candleviewer.storage.errors import StorageTierUnavailable

logger = structlog.get_logger(__name__)

_FLUSH_ROWS = 5_000
_FLUSH_INTERVAL_S = 0.1  # 100 ms, per Sec.4.14
_RECONNECT_BASE_S = 0.5
_RECONNECT_MAX_S = 30.0


class IlpTransport(Protocol):
    """The minimal socket surface the writer needs — a `Protocol` so tests
    supply an in-memory fake instead of a real TCP connection."""

    async def connect(self) -> None: ...

    async def write(self, data: bytes) -> None: ...

    async def close(self) -> None: ...


def _escape_symbol(value: str) -> str:
    """Escape a `SYMBOL`/tag value per ILP: space, comma and `=` are escaped
    with a backslash; nothing else needs escaping in this codebase's tag
    values (`side`, `action`, `regime`, ... are closed enums, not arbitrary
    user text)."""
    return value.replace(" ", r"\ ").replace(",", r"\,").replace("=", r"\=")


def _escape_string_field(value: str) -> str:
    """Escape a `STRING` field value: backslash and double-quote."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


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
    rows: list[tuple[dict[str, object], int]] = field(default_factory=list)
    last_flush: float = field(default_factory=time.monotonic)


class IlpWriter:
    """Batched ILP writer: one queue/buffer per table, flush at 5 000 rows
    or 100 ms (whichever first), bounded queue with explicit backpressure.

    Backpressure policy: the internal queue is bounded
    (`max_queue_rows`); when full, `write_rows` **awaits** queue space
    (never drops, never raises) so a slow/down QuestDB backs the caller up
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
    ) -> None:
        self._transport = transport
        self._schemas = schemas
        self._max_queue_rows = max_queue_rows
        self._flush_rows = flush_rows
        self._flush_interval_s = flush_interval_s
        self._buffers: dict[str, _TableBuffer] = {}
        self._total_buffered = 0
        self._not_full = asyncio.Event()
        self._not_full.set()
        self._connected = False
        self._reconnect_delay_s = _RECONNECT_BASE_S
        self._write_errors_total = 0
        self._rows_written_total = 0
        self._lock = asyncio.Lock()

    @property
    def rows_written_total(self) -> int:
        return self._rows_written_total

    @property
    def write_errors_total(self) -> int:
        return self._write_errors_total

    def queue_depth(self, table: str) -> int:
        buf = self._buffers.get(table)
        return len(buf.rows) if buf else 0

    async def start(self) -> None:
        await self._connect_with_backoff()

    async def _connect_with_backoff(self) -> None:
        while True:
            try:
                await self._transport.connect()
                self._connected = True
                self._reconnect_delay_s = _RECONNECT_BASE_S
                return
            except Exception as exc:
                self._write_errors_total += 1
                logger.warning(
                    "questdb_ilp_connect_failed",
                    error=str(exc),
                    retry_in_s=self._reconnect_delay_s,
                )
                await asyncio.sleep(self._reconnect_delay_s)
                self._reconnect_delay_s = min(self._reconnect_delay_s * 2, _RECONNECT_MAX_S)

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        """Buffer `rows` for `table`; applies backpressure (awaits, never
        drops) if the writer's total buffered-row budget is exhausted, then
        flushes `table` if its own flush threshold (5 000 rows or 100 ms) is
        met.

        The wait for queue space happens *outside* the lock — `flush()`
        needs the same lock to drain a buffer and signal `_not_full`, so
        holding it while waiting would deadlock the writer against its own
        flush path.
        """
        schema = self._schemas[table]
        while True:
            async with self._lock:
                if self._total_buffered + len(rows) <= self._max_queue_rows:
                    buf = self._buffers.setdefault(table, _TableBuffer(schema=schema))
                    for row in rows:
                        ts_us = int(str(row[ts_us_key]))
                        buf.rows.append((row, ts_us))
                    self._total_buffered += len(rows)
                    break
                self._not_full.clear()
            await self._not_full.wait()
        await self._maybe_flush(table)

    async def _maybe_flush(self, table: str) -> None:
        buf = self._buffers.get(table)
        if buf is None:
            return
        elapsed = time.monotonic() - buf.last_flush
        if len(buf.rows) >= self._flush_rows or elapsed >= self._flush_interval_s:
            await self.flush(table)

    async def flush(self, table: str | None = None) -> None:
        """Flush one table's buffer (or every table's, if `table` is
        `None` — used by `stop()`). Always exactly-once per buffered row:
        rows are cleared from the buffer only after a successful write."""
        tables = [table] if table is not None else list(self._buffers.keys())
        for name in tables:
            buf = self._buffers.get(name)
            if buf is None or not buf.rows:
                continue
            async with self._lock:
                rows_to_send = buf.rows
                buf.rows = []
                self._total_buffered -= len(rows_to_send)
                self._not_full.set()
            lines = [serialize_ilp_line(buf.schema, row, ts_us) for row, ts_us in rows_to_send]
            payload = ("\n".join(lines) + "\n").encode("utf-8")
            try:
                if not self._connected:
                    await self._connect_with_backoff()
                await self._transport.write(payload)
                self._rows_written_total += len(rows_to_send)
                buf.last_flush = time.monotonic()
            except Exception as exc:
                self._write_errors_total += 1
                self._connected = False
                async with self._lock:
                    buf.rows = rows_to_send + buf.rows
                    self._total_buffered += len(rows_to_send)
                    self._not_full.set()
                logger.error("questdb_ilp_write_failed", table=name, error=str(exc))
                raise StorageTierUnavailable(f"questdb ILP write failed for {name!r}") from exc

    async def stop(self) -> None:
        """Flush every buffered row, then close the transport. Idempotent."""
        try:
            await self.flush(None)
        finally:
            await self._transport.close()
            self._connected = False
