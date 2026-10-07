"""Async batched bars write path (E12-T02, #345; BR-34 bounded buffer).

Builders call `submit()` on the emit path; a single tracked drain task batches rows per table and
hands them to a sink with `IlpWriter.write_rows`'s shape (the composition root passes the real
`IlpWriter`, which owns reconnect/at-least-once/never-drop - `storage/questdb/ilp_writer.py`).

Never drops (C-2.18): the buffer is a bounded `asyncio.Queue`; a full buffer makes `submit()`
*await* space (counted + warned), it never discards. In-flight sink calls are bounded by a
semaphore. BR-34: a *new* spec is refused (`BarBufferFull`) while the buffer is saturated, so a
flood of fresh specs cannot starve established series; `healthy` is the signal for that.
Amended bars re-submit the same `(ts, symbol, bar_param)` and replace the row via DEDUP UPSERT.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Sequence
from typing import Protocol

import structlog

from candleviewer.bars.errors import BarsError
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.rows import (
    BAR_PARAM_CAPACITY,
    SOURCE_RANK,
    BarParamCapacityExceeded,
    bar_param_for,
    bar_row,
    table_for,
)
from candleviewer.observability.context import spawn
from candleviewer.observability.metrics import Counter, Gauge, Histogram

_log = structlog.get_logger(__name__)

bars_rows_written_total = Counter(
    "bars_rows_written_total", "Bar rows handed to QuestDB.", ["kind"]
)
bars_write_queue_depth = Gauge("bars_write_queue_depth", "Rows waiting in the bars write buffer.")
bars_write_saturation_total = Counter(
    "bars_write_saturation_total", "Submits that had to wait for buffer space (backpressure)."
)
bars_write_latency_seconds = Histogram(
    "bars_write_latency_seconds", "Wall time of one batched sink write."
)
bars_symbol_cardinality = Gauge(
    "bars_symbol_cardinality", "Distinct bar_param values seen per table.", ["table"]
)


bars_source_overwrite_refused_total = Counter(
    "bars_source_overwrite_refused_total",
    "Writes refused because a lower-precedence source would overwrite a higher one.",
    ["from_source", "to_source"],
)
#: Bound on the per-process precedence memory (LRU; SR-E12-05).
MAX_TRACKED_ROWS = 200_000


class SourceOverwriteRefused(BarsError):
    """SR-E12-10/BR-07: a kline row may not overwrite a tape row at the same dedup key."""


class BarBufferFull(BarsError):
    """BR-34: the write buffer is saturated; a new spec is refused (existing series still wait)."""


class RowSink(Protocol):
    async def write_rows(
        self, table: str, rows: list[dict[str, object]], ts_us_key: str
    ) -> None: ...


class BarWriter:
    def __init__(
        self,
        sink: RowSink,
        *,
        max_buffered: int = 10_000,
        batch_rows: int = 500,
        max_in_flight: int = 2,
        refuse_new_specs_at: float = 0.9,
        retry_s: float = 0.5,
    ) -> None:
        if max_buffered < 1 or batch_rows < 1 or max_in_flight < 1:
            raise ValueError("max_buffered, batch_rows and max_in_flight must be >= 1")
        self._sink = sink
        self._queue: asyncio.Queue[tuple[str, dict[str, object]]] = asyncio.Queue(max_buffered)
        self._batch_rows = batch_rows
        self._in_flight = asyncio.Semaphore(max_in_flight)
        self._retry_s = retry_s
        self._refuse_at = max(1, int(max_buffered * refuse_new_specs_at))
        self._params: dict[str, set[str]] = {}
        self._known_specs: set[tuple[str, str]] = set()
        self._task: asyncio.Task[None] | None = None
        self._pending: set[asyncio.Task[None]] = set()
        self._failure: Exception | None = None
        self._sources: OrderedDict[tuple[str, str, int], str] = OrderedDict()

    @property
    def healthy(self) -> bool:
        """False at/over the refusal watermark (a failing sink shows up as a growing buffer)."""
        return self._queue.qsize() < self._refuse_at

    @property
    def depth(self) -> int:
        return self._queue.qsize()

    async def start(self) -> None:
        if self._task is None:
            self._task = spawn(self._drain(), name="bars-writer-drain")

    def _admit_param(self, table: str, spec: BarSpec) -> None:
        key = (table, spec.spec_hash)
        if key in self._known_specs:
            return
        if not self.healthy:
            raise BarBufferFull("The bars write buffer is saturated; the new bar spec is refused.")
        params = self._params.setdefault(table, set())
        param = bar_param_for(spec)
        if param not in params and len(params) >= BAR_PARAM_CAPACITY:
            _log.error("bar_param_capacity_exceeded", table=table, capacity=BAR_PARAM_CAPACITY)
            raise BarParamCapacityExceeded(
                f"{table} already holds {BAR_PARAM_CAPACITY} bar_params."
            )
        params.add(param)
        bars_symbol_cardinality.labels(table).set(len(params))
        self._known_specs.add(key)

    def _check_precedence(
        self, table: str, spec: BarSpec, rows: list[dict[str, object]], source: str
    ) -> None:
        for row in rows:
            prior = self._sources.get(
                (table, spec.spec_hash + str(row["symbol"]), int(str(row["ts"])))
            )
            if prior is not None and SOURCE_RANK[source] < SOURCE_RANK[prior]:
                bars_source_overwrite_refused_total.labels(source, prior).inc()
                _log.warning("bars_source_overwrite_refused", table=table, spec_hash=spec.spec_hash)
                raise SourceOverwriteRefused(
                    f"A '{source}' bar may not overwrite an existing '{prior}' bar."
                )

    def _record_sources(
        self, table: str, spec: BarSpec, rows: list[dict[str, object]], source: str
    ) -> None:
        for row in rows:
            key = (table, spec.spec_hash + str(row["symbol"]), int(str(row["ts"])))
            self._sources[key] = source
            self._sources.move_to_end(key)
        while len(self._sources) > MAX_TRACKED_ROWS:
            self._sources.popitem(last=False)

    async def submit(self, bars: Sequence[Bar], spec: BarSpec, *, source: str = "tape") -> None:
        """Queue rows (validates all first: one bad, synthetic or lower-precedence bar rejects all).

        Precedence is enforced against rows written by this process; a read-side check against
        the stored row's `source` is the E12-T05 backfill caller's job (it owns the read path).
        """
        table = table_for(spec)
        rows = [bar_row(b, spec, source=source) for b in bars]
        self._check_precedence(table, spec, rows, source)
        self._admit_param(table, spec)
        self._record_sources(table, spec, rows, source)
        for row in rows:
            if self._queue.full():
                bars_write_saturation_total.inc()
                _log.warning("bars_write_saturated", depth=self._queue.qsize(), table=table)
            await self._queue.put((table, row))  # awaits space - never discards
        bars_write_queue_depth.set(self._queue.qsize())

    async def _drain(self) -> None:
        while True:
            table, row = await self._queue.get()
            batch = {table: [row]}
            while sum(map(len, batch.values())) < self._batch_rows and not self._queue.empty():
                t, r = self._queue.get_nowait()
                batch.setdefault(t, []).append(r)
            await self._in_flight.acquire()
            task = spawn(self._write(batch), name="bars-writer-batch")
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)

    async def _write(self, batch: dict[str, list[dict[str, object]]]) -> None:
        """Write one batch, retrying until it lands: a failed sink call never discards rows
        (the sink is idempotent via DEDUP UPSERT KEYS, so a resend is safe)."""
        try:
            for table, rows in batch.items():
                while True:
                    started = time.monotonic()
                    try:
                        await self._sink.write_rows(table, rows, "ts")
                    except Exception as exc:
                        self._failure = exc
                        _log.error("bars_write_failed", table=table, error=type(exc).__name__)
                        await asyncio.sleep(self._retry_s)
                        continue
                    self._failure = None
                    break
                bars_write_latency_seconds.observe(time.monotonic() - started)
                bars_rows_written_total.labels(table.removeprefix("bars_")).inc(len(rows))
                for _ in rows:
                    self._queue.task_done()
        finally:
            self._in_flight.release()
            bars_write_queue_depth.set(self._queue.qsize())

    async def stop(self) -> None:
        """Wait until every queued row is written, then stop the drain task."""
        await self._queue.join()
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
