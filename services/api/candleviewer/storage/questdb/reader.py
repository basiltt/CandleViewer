"""PGWire (8812) async reader for the QuestDB hot tier (E07-T03).

`docs/plan/21-database-schema.md` Sec.13.2 shapes 1-11: every query builder
here (a) filters on `symbol` by equality, (b) bounds `ts` on both sides
(where the shape has a range), and (c) never `ORDER BY`s a non-timestamp
column — a lint test (`tests/unit/storage/questdb/test_query_builders.py`)
parses each builder's SQL and asserts these three properties.

Parameterised queries only — no string interpolation of user input
(`docs/plan/04-security-program.md` Sec.5.8 SR-047: `SYMBOL`/interval values
are the only user-controlled predicate and must reach SQL only as bind
parameters, never f-string'd into the query text).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from candleviewer.storage.models import TimeRange
from candleviewer.storage.sql_identifiers import checked_identifier


@dataclass(frozen=True, slots=True)
class QueryBuilder:
    """A parameterised SQL string plus its bind parameters, in order."""

    sql: str
    params: tuple[object, ...]


#: `bar_<family>` table names are built from this closed allowlist, never
#: from raw caller input, before being spliced into SQL (SR-047: the only
#: user-controlled predicates are bind parameters).
_BAR_FAMILIES = ("time", "tick", "volume", "range", "renko", "delta")


def build_read_bars(sym: str, family: str, param: str, rng: TimeRange) -> QueryBuilder:
    """Shape #1 (chart bootstrap): `bars_<family> WHERE symbol=$1 AND
    bar_param=$2 AND ts BETWEEN $3 AND $4 ORDER BY ts`."""
    if family not in _BAR_FAMILIES:
        raise ValueError(f"unknown bar family {family!r}")
    table = f"bars_{family}"
    sql = (
        f"SELECT * FROM {table} WHERE symbol = $1 AND bar_param = $2 "  # noqa: S608  # nosec B608 - table from _BAR_FAMILIES allowlist, not user input
        "AND ts >= $3 AND ts < $4 ORDER BY ts"
    )
    return QueryBuilder(sql, (sym, param, rng.start_us, rng.end_us))


def build_read_trades(sym: str, rng: TimeRange) -> QueryBuilder:
    """Shape #4-adjacent plain trade range read."""
    sql = "SELECT * FROM trades WHERE symbol = $1 AND ts >= $2 AND ts < $3 ORDER BY ts"
    return QueryBuilder(sql, (sym, rng.start_us, rng.end_us))


def build_read_klines(sym: str, interval: str, rng: TimeRange) -> QueryBuilder:
    """E08-S06 cache read: `klines WHERE symbol=$1 AND interval=$2 AND ts
    BETWEEN $3 AND $4 ORDER BY ts` — same three-property shape every other
    builder here follows (symbol equality, two-sided ts bound, ts-ordered)."""
    sql = (
        "SELECT * FROM klines WHERE symbol = $1 AND interval = $2 "
        "AND ts >= $3 AND ts < $4 ORDER BY ts"
    )
    return QueryBuilder(sql, (sym, interval, rng.start_us, rng.end_us))


def build_read_funding(sym: str, rng: TimeRange, limit: int) -> QueryBuilder:
    """E24-T02 settled funding series: symbol equality, two-sided ts bound,
    ts-ordered, hard row cap (`limit` is a validated int, still bound)."""
    sql = (
        "SELECT ts, symbol, funding_rate, annualised_pct, interval_min, source "
        "FROM funding_rates WHERE symbol = $1 AND ts >= $2 AND ts < $3 "
        "ORDER BY ts LIMIT $4"
    )
    return QueryBuilder(sql, (sym, rng.start_us, rng.end_us, limit))


def build_read_big_trades(sym: str, rng: TimeRange, min_notional: float) -> QueryBuilder:
    """Shape #4 (big-trade bubbles): precomputed `notional` column."""
    sql = (
        "SELECT * FROM trades WHERE symbol = $1 AND notional > $2 "
        "AND ts >= $3 AND ts < $4 ORDER BY ts"
    )
    return QueryBuilder(sql, (sym, min_notional, rng.start_us, rng.end_us))


def build_latest_ticker(sym: str) -> QueryBuilder:
    """Shape #5 (last price): `LATEST ON ts PARTITION BY symbol`."""
    sql = "SELECT * FROM tickers WHERE symbol = $1 LATEST ON ts PARTITION BY symbol"
    return QueryBuilder(sql, (sym,))


def build_read_heatmap_trail(sym: str, since_ts_us: int) -> QueryBuilder:
    """Shape #6 (DOM heatmap trail): `WHERE symbol=$1 AND ts > now()-60s`."""
    sql = "SELECT * FROM heatmap_cells WHERE symbol = $1 AND ts > $2 ORDER BY ts"
    return QueryBuilder(sql, (sym, since_ts_us))


def build_read_book_snapshot_at(sym: str, ts_us: int) -> QueryBuilder:
    """Shape #7 (replay seek), snapshot half: nearest snapshot at/before
    `ts_us`."""
    sql = (
        "SELECT * FROM orderbook_snapshots WHERE symbol = $1 AND ts <= $2 ORDER BY ts DESC LIMIT 1"
    )
    return QueryBuilder(sql, (sym, ts_us))


def build_read_book_deltas(sym: str, rng: TimeRange) -> QueryBuilder:
    """Shape #7 (replay seek), deltas-forward half."""
    sql = "SELECT * FROM orderbook_deltas WHERE symbol = $1 AND ts >= $2 AND ts < $3 ORDER BY ts"
    return QueryBuilder(sql, (sym, rng.start_us, rng.end_us))


def build_read_orderflow_metrics(sym: str, metric: str, rng: TimeRange) -> QueryBuilder:
    """Shape #8 (CVD pane): a single metric column is read per call at the
    repository layer (the `metric` name selects the column, never
    concatenated into SQL — see `read_orderflow_metrics` in `repository.py`
    for the allowlist check), so this builder returns the full row and lets
    the caller project the column in Python."""
    sql = (
        "SELECT ts, symbol, cvd, cvd_session, delta_1s, trades_per_sec, "
        "notional_per_sec, buy_ratio, book_imbalance, book_thickness, "
        "spread_ticks, realized_vol_1m, atr_14, regime, regime_confidence, "
        "stacked_imbalance_up, stacked_imbalance_down, iceberg_score, "
        "stoprun_score, absorption_score FROM orderflow_metrics "
        "WHERE symbol = $1 AND ts >= $2 AND ts < $3 ORDER BY ts"
    )
    return QueryBuilder(sql, (sym, rng.start_us, rng.end_us))


def build_read_profile(sym: str, profile_kind: str, period_ref: str) -> QueryBuilder:
    """Shape #9 (profile panel)."""
    sql = (
        "SELECT * FROM profiles WHERE symbol = $1 AND profile_kind = $2 "
        "AND period_ref = $3 ORDER BY ts"
    )
    return QueryBuilder(sql, (sym, profile_kind, period_ref))


def build_read_footprint_cells(
    sym: str, bar_family: str, bar_param: str, rng: TimeRange
) -> QueryBuilder:
    """Shape #2 (footprint render)."""
    sql = (
        "SELECT * FROM footprint_cells WHERE symbol = $1 AND bar_family = $2 "
        "AND bar_param = $3 AND ts >= $4 AND ts < $5 ORDER BY ts"
    )
    return QueryBuilder(sql, (sym, bar_family, bar_param, rng.start_us, rng.end_us))


def build_asof_trades_to_tickers(sym: str, rng: TimeRange) -> QueryBuilder:
    """Shape #11 (trade<->book alignment): `ASOF JOIN`."""
    sql = (
        "SELECT t.ts, t.price, t.size, tk.mark_price, tk.index_price "
        "FROM trades t ASOF JOIN tickers tk ON (symbol) "
        "WHERE t.symbol = $1 AND t.ts >= $2 AND t.ts < $3 ORDER BY t.ts"
    )
    return QueryBuilder(sql, (sym, rng.start_us, rng.end_us))


class PgWireConnection(Protocol):
    """The minimal `asyncpg`-shaped surface the reader needs — a `Protocol`
    so tests supply an in-memory fake."""

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]: ...


class QuestDbReader:
    """Thin wrapper binding `QueryBuilder`s to a `PgWireConnection`. The
    connection pool itself (asyncpg `create_pool`, read-only role) is wired
    by `StorageService.start()` in the `real` backend — this class takes an
    already-connected pool/connection so it stays trivially testable."""

    def __init__(self, connection: PgWireConnection) -> None:
        self._conn = connection

    async def run(self, builder: QueryBuilder) -> list[dict[str, object]]:
        return await self._conn.fetch(builder.sql, *builder.params)


def pgwire_readiness_probe(connection: PgWireConnection) -> Callable[[], Awaitable[bool]]:
    """Production readiness probe for `IlpWriter(readiness_probe=...)`: a
    `SELECT 1` over PG-wire; any error or empty result means not ready."""

    async def probe() -> bool:
        try:
            return bool(await connection.fetch("SELECT 1"))
        except Exception:
            return False

    return probe


def pgwire_committed_counter(
    connection: PgWireConnection, tables: Sequence[str]
) -> Callable[[], Awaitable[int]]:
    """Total committed rows across `tables` for `IlpWriter(committed_counter=...)`.
    Table names cannot be bound, so each is validated as a plain identifier
    up front (fail at wiring time, not on the first count)."""
    queries = tuple(
        " ".join(("SELECT count() AS n FROM", checked_identifier(table))) for table in tables
    )

    async def count() -> int:
        total = 0
        for query in queries:
            rows = await connection.fetch(query)
            total += int(cast(int, rows[0]["n"])) if rows else 0
        return total

    return count
