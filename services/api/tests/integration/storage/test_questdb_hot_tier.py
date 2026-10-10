"""Integration tests for the QuestDB hot tier (E07-T03).

Runs against a real QuestDB 8.x container (ILP-over-TCP on 9009, PGWire on
8812) via `testcontainers`. Requires Docker; not run locally in this
environment (no docker installed) — exercised in CI's `integration` job.

Covers the ticket's Gherkin ACs that need a real engine:
- DDL runner applies all tables with WAL + DEDUP UPSERT KEYS, idempotent on
  a second run (`_cv_migrations` records applied files, no re-apply).
- Writing the same fixture trades twice (simulating resubscribe-on-gap)
  leaves the row count unchanged (DEDUP UPSERT KEYS idempotency end-to-end).
- Schema drift: mutating a live table's columns raises `StorageSchemaDrift`.

The QuestDB demo container's default PGWire credentials (`admin`/`quest`)
are not a secret — they are QuestDB's own well-known local-dev default,
documented at https://questdb.io, never a real credential (C-2.7 concerns
production keys, not this fixed OSS default used only against an ephemeral
test container).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from candleviewer.storage.errors import StorageSchemaDrift
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.reader import QuestDbReader
from candleviewer.storage.questdb.repository import QuestDbMarketDataRepository
from candleviewer.storage.questdb.runner import assert_no_schema_drift, run_migrations
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS
from candleviewer.storage.repositories.rows import TradeRow

pytestmark = pytest.mark.integration

DDL_DIR = Path(__file__).resolve().parents[5] / "backend" / "db" / "questdb"

_PGWIRE_USER = "admin"
_PGWIRE_PASSWORD = "quest"  # noqa: S105 -- QuestDB OSS demo-container default, not a secret.


async def _wait_for_column(
    conn: asyncpg.Connection, table: str, column: str, *, attempts: int = 50
) -> None:
    """Poll QuestDB's `table_columns()` until `column` is visible on `table`.

    Bounded (attempts x 100 ms = 5 s); raises AssertionError with the last seen
    column set if the DDL never becomes visible, so a real regression in DDL
    application still fails loudly instead of masquerading as drift-not-detected.
    """
    seen: set[str] = set()
    for _ in range(attempts):
        rows = await conn.fetch(f"SELECT \"column\" FROM table_columns('{table}')")  # noqa: S608  # nosec B608 - test-owned literal table name
        seen = {str(r["column"]).lower() for r in rows}
        if column in seen:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"column {column!r} never appeared on {table!r}; last seen {sorted(seen)}")


async def wait_for_row_count(
    conn: asyncpg.Connection,
    table: str,
    expected: int,
    *,
    timeout_s: float = 60.0,
    interval_s: float = 0.2,
) -> None:
    """Wait until QuestDB's WAL apply has made exactly `expected` rows of
    `table` visible AND the table's writer has caught up with its sequencer.

    ILP/TCP is fire-and-forget and WAL apply is asynchronous, so callers must
    first `flush()`/`stop()` the `IlpWriter` (drains the socket) and then call
    this. Bounded (`timeout_s`, C-2.18); on timeout raises AssertionError with
    the last observed count and the `wal_tables()` row (suspended flag,
    writerTxn vs sequencerTxn) so a rejected/suspended write is diagnosable.
    """
    count = -1
    wal: dict[str, object] = {}
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        count = int(await conn.fetchval(f"SELECT count() FROM {table}"))  # noqa: S608  # nosec B608 - test-owned literal table name
        wal_rows = await conn.fetch("SELECT * FROM wal_tables() WHERE name = $1", table)
        wal = dict(wal_rows[0]) if wal_rows else {}
        caught_up = wal.get("writerTxn") == wal.get("sequencerTxn")
        if count == expected and caught_up:
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(
                f"{table}: expected {expected} rows after WAL apply, observed {count} "
                f"after {timeout_s}s; wal_tables()={wal}"
            )
        await asyncio.sleep(interval_s)


async def _connect(host: str, port: int) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=host, port=port, user=_PGWIRE_USER, password=_PGWIRE_PASSWORD, database="qdb"
    )


class _AsyncpgExecutor:
    """Adapts an `asyncpg.Connection` to the runner's `QuestDbExecutor`
    Protocol (`execute`/`fetch` returning `list[dict]`)."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def execute(self, sql: str, *args: object) -> None:
        await self._conn.execute(sql, *args)

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        rows = await self._conn.fetch(sql, *args)
        return [dict(r) for r in rows]


class _AsyncpgTcpIlpTransport:
    """Minimal ILP-over-TCP transport (`IlpTransport` Protocol) using
    `asyncio.open_connection` against QuestDB's line-protocol port (9009)."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        _, writer = await asyncio.open_connection(self._host, self._port)
        self._writer = writer

    async def write(self, data: bytes) -> None:
        assert self._writer is not None
        self._writer.write(data)
        await self._writer.drain()

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()


@pytest_asyncio.fixture
async def questdb_container() -> AsyncIterator[tuple[str, int, int]]:
    from testcontainers.core.container import DockerContainer

    container = (
        DockerContainer("questdb/questdb:8.1.1")
        .with_exposed_ports(8812, 9009)
        .with_env("QDB_PG_READONLY_USER_ENABLED", "true")
    )
    with container:
        host = container.get_container_host_ip()
        pg_port = int(container.get_exposed_port(8812))
        ilp_port = int(container.get_exposed_port(9009))
        for _ in range(60):
            try:
                conn = await _connect(host, pg_port)
                await conn.close()
                break
            except OSError:
                await asyncio.sleep(1.0)
        yield host, pg_port, ilp_port


@pytest.mark.asyncio
async def test_ddl_runner_applies_all_tables_idempotently(
    questdb_container: tuple[str, int, int],
) -> None:
    host, pg_port, _ = questdb_container
    conn = await _connect(host, pg_port)
    try:
        executor = _AsyncpgExecutor(conn)
        applied_first = await run_migrations(executor, DDL_DIR)
        assert applied_first == [
            "0001_core_tables.sql",
            "0002_footprint_cells.sql",
            "0003_bars_integrity_columns.sql",
            "0004_bars_key_by_index.sql",
        ]
        await assert_no_schema_drift(executor, DDL_DIR)

        applied_second = await run_migrations(executor, DDL_DIR)
        assert applied_second == []  # idempotent: nothing re-applied
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_write_trades_dedup_replay_is_idempotent(
    questdb_container: tuple[str, int, int],
) -> None:
    host, pg_port, ilp_port = questdb_container
    conn = await _connect(host, pg_port)
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)

        transport = _AsyncpgTcpIlpTransport(host, ilp_port)
        writer = IlpWriter(transport, ALL_SCHEMAS)
        await writer.start()
        reader = QuestDbReader(conn)
        repo = QuestDbMarketDataRepository(writer, reader)

        rows = [
            TradeRow(
                ts_us=1_700_000_000_000_000 + i,
                symbol="BTCUSDT",
                price="65000.5",
                qty="0.01",
                side="buy",
                trade_id=f"t{i}",
            )
            for i in range(10)
        ]
        await repo.write_trades(rows)
        await writer.flush("trades")
        # Simulate resubscribe-on-gap: replay the identical batch.
        await repo.write_trades(rows)
        await writer.flush("trades")
        await writer.stop()

        # QuestDB WAL apply/dedup is asynchronous; event-based bounded wait.
        await wait_for_row_count(conn, "trades", 10)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_schema_drift_detected_when_live_columns_differ(
    questdb_container: tuple[str, int, int],
) -> None:
    host, pg_port, _ = questdb_container
    conn = await _connect(host, pg_port)
    try:
        executor = _AsyncpgExecutor(conn)
        await run_migrations(executor, DDL_DIR)
        await conn.execute("ALTER TABLE trades ADD COLUMN unexpected_extra DOUBLE")
        # QuestDB applies ALTER TABLE asynchronously (the writer thread commits
        # the metadata change after the statement returns), so a follow-up
        # `table_columns()` read can still see the old column set — observed as
        # a "DID NOT RAISE StorageSchemaDrift" flake on unrelated PRs (#1603).
        # Wait (bounded) until introspection reflects the new column before
        # asserting; the drift check itself is unchanged.
        await _wait_for_column(conn, "trades", "unexpected_extra")
        with pytest.raises(StorageSchemaDrift):
            await assert_no_schema_drift(executor, DDL_DIR)
    finally:
        await conn.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bars_sink_writes_row_readable_over_pgwire(
    questdb_container: tuple[str, int, int],
) -> None:
    from candleviewer.storage.questdb.wiring import QuestDbRowSink

    host, pg_port, ilp_port = questdb_container
    conn = await _connect(host, pg_port)
    sink = QuestDbRowSink(f"{host}:{ilp_port}", f"{host}:{pg_port}", _PGWIRE_USER, _PGWIRE_PASSWORD)
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)
        row: dict[str, object] = {
            "symbol": "BTCUSDT",
            "bar_param": "60000",
            "ts": 1_700_000_000_000_000,
        }
        row |= {
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 3.0,
            "is_closed": True,
        }
        await sink.write_rows("bars_time", [row], "ts")
        await sink.stop()
        await wait_for_row_count(conn, "bars_time", 1)
    finally:
        await conn.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_read_bars_order_by_ts_then_index_executes_on_real_questdb(
    questdb_container: tuple[str, int, int],
) -> None:
    """#2016: the reader's `ORDER BY ts, "index"` and bind count must run on a real QuestDB."""
    from candleviewer.bars.reader import build_range_query
    from candleviewer.storage.questdb.wiring import QuestDbRowSink

    host, pg_port, ilp_port = questdb_container
    conn = await _connect(host, pg_port)
    sink = QuestDbRowSink(f"{host}:{ilp_port}", f"{host}:{pg_port}", _PGWIRE_USER, _PGWIRE_PASSWORD)
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)
        base: dict[str, object] = {
            "symbol": "BTCUSDT", "bar_param": "vol:1500", "ts": 1_700_000_000_000_000,
            "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1500.0,
            "is_closed": True, "generation": 0,
        }  # fmt: skip
        rows = [{**base, "index": i} for i in (2, 0, 1)]  # same ts: only the index differs
        await sink.write_rows("bars_volume", rows, "ts")
        await sink.stop()
        await wait_for_row_count(conn, "bars_volume", 3)
        sql, params = build_range_query("volume", "BTCUSDT", "vol:1500", 0, 2**60, None, 10)
        got = await conn.fetch(sql, *params)
        assert [r["index"] for r in got] == [0, 1, 2]
    finally:
        await conn.close()
