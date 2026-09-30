"""DuckDB view layer over the Parquet lake — `21-database-schema.md` Sec.5.5.

Views hold no state and are rebuilt from source on every start. DuckDB runs
in-process only (SR-048: no server mode, no port). The optional Postgres
attachment is `READ_ONLY` as the `cv_ro` role, so analytics can never mutate
the ledger. No `INSTALL` is issued for the Parquet path (the reader is built
in), so building the lake views needs no network; the `postgres` extension
is only installed/loaded when a DSN is supplied (deployment-time).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.models import StreamKind

#: View name -> registered stream (Sec.5.5's worked list).
VIEW_STREAMS: dict[str, StreamKind] = {
    "trades": StreamKind.TRADES,
    "orderbook_deltas": StreamKind.ORDERBOOK_DELTA,
    "bars": StreamKind.BARS,
    "footprint_cells": StreamKind.FOOTPRINT_CELLS,
}

#: OMS-sourced views (producers are E41/E29); `oms/<name>/ym=*/`.
_OMS_VIEWS: dict[str, str] = {
    "executions_cold": "executions",
    "journal_cold": "journal_trades",
}

_EMPTY_MARKET_VIEW = (
    "SELECT NULL::VARCHAR AS symbol, NULL::VARCHAR AS dt, "
    "NULL::TIMESTAMPTZ AS ts, NULL::DOUBLE AS price, NULL::DOUBLE AS size, "
    "NULL::DOUBLE AS notional, NULL::VARCHAR AS side WHERE false"
)


def _sql_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _create_parquet_view(con: duckdb.DuckDBPyConnection, name: str, glob: str) -> bool:
    """`name` comes from the fixed tables above and `glob` is built only from
    the registry templates and `CV_COLD_ROOT` (never caller text), so the
    inlined literal is safe; DuckDB cannot bind parameters in DDL."""
    sql = (
        f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet("  # noqa: S608  # nosec B608 - fixed view name + registry glob
        f"{_sql_literal(glob)}, hive_partitioning = true, union_by_name = true)"
    )
    try:
        con.execute(sql)
    except duckdb.IOException:
        return False
    return True


class UnsafeAnalyticsDsn(ValueError):
    """The Postgres DSN for the analytics attachment is not a plain `cv_ro`
    key/value DSN (SR-048: analytics must never hold a writable role)."""


_DSN_FORBIDDEN = frozenset((chr(39), chr(34), ";", chr(10), chr(13)))  # quote, dquote, ;, LF, CR


def _checked_ro_dsn(dsn: str) -> str:
    """Accept only a libpq key/value DSN for the `cv_ro` role with no quote,
    semicolon or newline characters. The DSN is never logged."""
    if any(ch in dsn for ch in _DSN_FORBIDDEN) or "user=cv_ro" not in dsn.split():
        raise UnsafeAnalyticsDsn("analytics attachment requires a plain cv_ro key/value DSN")
    return dsn


def build_views(db_path: Path, registry: DatasetRegistry, *, pg_dsn: str | None = None) -> None:
    """(Re)create every cold-tier view in `db_path` (idempotent)."""
    con = duckdb.connect(str(db_path))
    try:
        con.execute("SET TimeZone = 'UTC'")
        for view_name, stream in VIEW_STREAMS.items():
            if not _create_parquet_view(con, view_name, registry.dataset_glob(stream)):
                # Not yet exported: a typed empty view so queries return 0 rows.
                # nosemgrep: cv-raw-sql-string-interpolation -- view_name is a VIEW_STREAMS key
                con.execute(f"CREATE OR REPLACE VIEW {view_name} AS {_EMPTY_MARKET_VIEW}")
        oms_ok: dict[str, bool] = {}
        for view_name, sub in _OMS_VIEWS.items():
            glob = (registry.root / "oms" / sub / "*" / "*.parquet").as_posix()
            oms_ok[view_name] = _create_parquet_view(con, view_name, glob)

        journal_parts = ["SELECT * FROM journal_cold"] if oms_ok["journal_cold"] else []
        if pg_dsn:
            con.execute("INSTALL postgres")
            con.execute("LOAD postgres")
            con.execute("DETACH DATABASE IF EXISTS pg")
            dsn = _checked_ro_dsn(pg_dsn)
            # ATTACH has no bind params (DuckDB grammar); DSN validated above.
            # nosemgrep: cv-raw-sql-string-interpolation
            con.execute(f"ATTACH {_sql_literal(dsn)} AS pg (TYPE postgres, READ_ONLY)")
            journal_parts.append(
                "SELECT * FROM pg.public.journal_trades "
                "WHERE opened_at >= (current_date - INTERVAL 90 DAY)"
            )
        if journal_parts:
            # nosemgrep: cv-raw-sql-string-interpolation -- parts are the two fixed literals above
            con.execute(
                "CREATE OR REPLACE VIEW journal_all AS " + " UNION ALL BY NAME ".join(journal_parts)
            )
            con.execute(
                "CREATE OR REPLACE VIEW v_daily_pnl AS "
                "SELECT date_trunc('day', opened_at) AS d, exchange_account_id, env, "
                "sum(net_pnl) AS net_pnl, count(*) AS trades, "
                "sum(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END)::DOUBLE"
                " / nullif(count(*), 0) AS win_rate, avg(r_multiple) AS avg_r "
                "FROM journal_all GROUP BY 1, 2, 3"
            )
        con.execute(
            "CREATE OR REPLACE VIEW v_session_tape_stats AS "
            "SELECT symbol, date_trunc('hour', ts) AS h, count(*) AS prints, "
            "sum(notional) AS notional, "
            "sum(CASE WHEN side = 'Buy' THEN size ELSE -size END) AS delta "
            "FROM trades GROUP BY 1, 2"
        )
    finally:
        con.close()


def query_symbol_day_count(db_path: Path, view: str, symbol: str, dt: str) -> int:
    """R0 exit criterion #6: `SELECT count(*) FROM <view> WHERE symbol=? AND
    dt=?`. `view` must be a registered view name; values are bound."""
    if view not in VIEW_STREAMS:
        raise ValueError(f"unregistered view: {view!r}")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute(
            f"SELECT count(*) FROM {view} WHERE symbol = ? AND dt = ?",  # noqa: S608  # nosec B608 - view checked against VIEW_STREAMS
            [symbol, dt],
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        con.close()
