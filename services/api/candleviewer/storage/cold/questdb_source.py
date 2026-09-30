"""`HotTierSource` over QuestDB PGWire (E07-T03's `PgWireConnection`).

Table names come from a closed allowlist keyed by `StreamKind` (SR-047);
symbol, range and paging values are bind parameters. Reads are paged with
QuestDB's `LIMIT lo, hi` over `ORDER BY ts, price` on a *closed* partition,
so each page is bounded (`batch_rows`) and the whole day is never
materialised. Each page fetch is bounded by `page_timeout_s` (C-2.18).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pyarrow as pa

from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.questdb.reader import PgWireConnection


def _us_to_datetime(value_us: int) -> datetime:
    """QuestDB's `TIMESTAMP` columns are bound over PGWire as `datetime`
    (asyncpg's `timestamptz` codec rejects raw microsecond ints) — every
    `ts` bind parameter here must go through this conversion, never the
    bare `TimeRange` int. QuestDB reports its `TIMESTAMP` type as
    PostgreSQL's tz-naive `timestamp` (not `timestamptz`) over PGWire, so
    asyncpg's codec requires a naive `datetime` here — a tz-aware value
    raises `DataError` ("can't subtract offset-naive and offset-aware
    datetimes") deep in the codec. Convert to UTC first, then strip
    `tzinfo`, so the wall-clock value still matches the UTC microseconds
    QuestDB stores."""
    return datetime.fromtimestamp(value_us / 1_000_000, tz=UTC).replace(tzinfo=None)


#: Stream -> (QuestDB table, secondary sort column). Streams without a
#: `price` column sort by `ts` only.
_TABLES: dict[StreamKind, tuple[str, str | None]] = {
    StreamKind.TRADES: ("trades", "price"),
    StreamKind.ORDERBOOK_DELTA: ("orderbook_deltas", "price"),
    StreamKind.TICKERS: ("tickers", None),
    StreamKind.LIQUIDATIONS: ("liquidations", "price"),
}


class UnsupportedExportStream(ValueError):
    """No hot-tier table is registered for this stream's export."""


def _table_for(stream: StreamKind) -> tuple[str, str | None]:
    try:
        return _TABLES[stream]
    except KeyError as exc:
        raise UnsupportedExportStream(f"no hot-tier export mapping for {stream!r}") from exc


class QuestDbHotTierSource:
    """Adapts a PGWire connection to the exporter's `HotTierSource`."""

    def __init__(self, connection: PgWireConnection, *, page_timeout_s: float = 60.0) -> None:
        self._conn = connection
        self._timeout = page_timeout_s

    async def count_partition(self, symbol: str, stream: StreamKind, rng: TimeRange) -> int:
        table, _ = _table_for(stream)
        sql = f"SELECT count(*) AS n FROM {table} WHERE symbol = $1 AND ts >= $2 AND ts < $3"  # noqa: S608  # nosec B608 - table from _TABLES allowlist
        async with asyncio.timeout(self._timeout):
            rows = await self._conn.fetch(
                sql, symbol, _us_to_datetime(rng.start_us), _us_to_datetime(rng.end_us)
            )
        value = rows[0]["n"] if rows else 0
        return int(value) if isinstance(value, int) else int(str(value))

    async def iter_partition(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, batch_rows: int
    ) -> AsyncIterator[pa.Table]:
        table, secondary = _table_for(stream)
        order = "ts, price" if secondary else "ts"
        offset = 0
        while True:
            # QuestDB's PGWire `LIMIT lo, hi` does not accept bind parameters
            # for the paging bounds (it rejects the prepared statement with
            # "the server expects 3 arguments"), so `offset`/`offset +
            # batch_rows` are inlined as literals here — both are ints this
            # method computes itself (never user input), so there is no
            # injection surface.
            sql = (
                f"SELECT * FROM {table} WHERE symbol = $1 AND ts >= $2 AND ts < $3 "  # noqa: S608  # nosec B608 - table/order from _TABLES allowlist
                f"ORDER BY {order} LIMIT {offset}, {offset + batch_rows}"  # nosec B608 - int paging bounds, not user input
            )
            async with asyncio.timeout(self._timeout):
                rows = await self._conn.fetch(
                    sql,
                    symbol,
                    _us_to_datetime(rng.start_us),
                    _us_to_datetime(rng.end_us),
                )
            if not rows:
                return
            yield pa.Table.from_pylist(rows)
            if len(rows) < batch_rows:
                return
            offset += len(rows)
