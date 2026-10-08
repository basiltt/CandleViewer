"""Production composition of the QuestDB ILP writer (#1701).

`build_hot_tier_writer` is the single place that attaches the PG-wire
readiness probe and committed-row counter, so no caller can build an
unguarded writer by accident. `run_reconcile_loop` periodically compares
rows sent vs committed and exports the gap as `questdb_ilp_unreconciled_rows`
(alert on > 0 sustained).
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import asyncpg

from candleviewer.observability.metrics import Metrics
from candleviewer.storage.questdb.ilp_writer import IlpTransport, IlpWriter, TableSchema
from candleviewer.storage.questdb.reader import (
    PgWireConnection,
    pgwire_committed_counter,
    pgwire_readiness_probe,
)
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS


def build_hot_tier_writer(
    transport: IlpTransport,
    schemas: dict[str, TableSchema],
    connection: PgWireConnection,
    **kwargs: object,
) -> IlpWriter:
    """`IlpWriter` with readiness probe + committed counter always wired.
    The counter is `count()` over every schema table: it MUST be cumulative
    (monotonic) — `IlpWriter` baselines it once at first connect."""
    return IlpWriter(
        transport,
        schemas,
        readiness_probe=pgwire_readiness_probe(connection),
        committed_counter=pgwire_committed_counter(connection, tuple(schemas)),
        **kwargs,  # type: ignore[arg-type]  # forwarded tuning knobs (max_queue_rows, ...)
    )


async def run_reconcile_loop(
    writer: IlpWriter,
    metrics: Metrics,
    *,
    interval_s: float = 30.0,
    iterations: int | None = None,
) -> None:
    """Every `interval_s`, reconcile and set the gap gauge. Probe failures are
    counted, never fatal. `iterations` bounds the loop for tests."""
    gap_gauge = metrics.gauge(
        "questdb_ilp_unreconciled_rows",
        "ILP rows sent but not (yet) committed per QuestDB count().",
    ).child()
    errors = metrics.counter(
        "questdb_ilp_reconcile_errors_total", "Failed sent-vs-committed reconcile attempts."
    ).child()
    done = 0
    while iterations is None or done < iterations:
        await asyncio.sleep(interval_s)
        try:
            await writer.reconcile()
            gap_gauge.set(writer.unreconciled_rows)
        except Exception:
            errors.inc()
        done += 1


class TcpIlpTransport:
    """ILP-over-TCP `IlpTransport` (QuestDB line-protocol port)."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        _, self._writer = await asyncio.open_connection(self._host, self._port)

    async def write(self, data: bytes) -> None:
        if self._writer is None:
            raise ConnectionError("ILP transport is not connected")
        self._writer.write(data)
        await self._writer.drain()

    async def close(self) -> None:
        writer, self._writer = self._writer, None
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()


class LazyPgWire:
    """`PgWireConnection` that opens one asyncpg connection on first use and reopens it after a
    failure, so the app boots (and the ILP writer retries) while QuestDB is down."""

    def __init__(self, host: str, port: int, user: str, password: str) -> None:
        self._args: dict[str, Any] = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": "qdb",
        }
        self._conn: Any = None

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        try:
            if self._conn is None:
                self._conn = await asyncpg.connect(**self._args, timeout=5.0)
            rows = await self._conn.fetch(sql, *params)
        except Exception:
            await self.close()
            raise
        return [dict(r) for r in rows]

    async def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            with contextlib.suppress(Exception):
                await conn.close()


class QuestDbRowSink:
    """Bars `RowSink` over the hot-tier `IlpWriter` (transport + PG-wire via
    `build_hot_tier_writer`). The writer connects on first flush (retrying with backoff);
    `stop()` drains it, closes the transport, then the PG-wire connection."""

    def __init__(
        self,
        ilp: str,
        pg: str,
        user: str,
        password: str,
        *,
        transport: IlpTransport | None = None,
        pgwire: LazyPgWire | None = None,
    ) -> None:
        ilp_host, _, ilp_port = ilp.partition(":")
        pg_host, _, pg_port = pg.partition(":")
        self.pgwire = pgwire or LazyPgWire(pg_host, int(pg_port or 8812), user, password)
        self.writer = build_hot_tier_writer(
            transport or TcpIlpTransport(ilp_host, int(ilp_port or 9009)),
            ALL_SCHEMAS,
            self.pgwire,
        )

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        await self.writer.write_rows(table, rows, ts_us_key)

    async def stop(self) -> None:
        try:
            await self.writer.stop()  # drains, then closes the ILP transport
        finally:
            await self.pgwire.close()
