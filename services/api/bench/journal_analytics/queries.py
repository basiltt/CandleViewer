# ruff: noqa: S608  # bench-only SQL text; ids are validated by _lit(), values are synthetic
"""SQL for the journal analytics tiers (identical text runs on Postgres and DuckDB).

RBAC (E41-K01): every query is built through :func:`scoped_from`, which always wraps the base
table in a mandatory ``exchange_account_id = ANY(granted)`` predicate.  A caller-supplied
account filter can only *narrow* inside that scope (intersection), never widen it.
"""

from __future__ import annotations

from collections.abc import Sequence

BREAKDOWNS: dict[str, str] = {
    "symbol": "t.symbol",
    "side": "t.side",
    "account": "t.exchange_account_id::text",
    "setup": "coalesce(t.setup_name, '-')",
    "hour_of_day": "extract(hour FROM t.opened_at)::int::text",
    "day_of_week": "extract(dow FROM t.opened_at)::int::text",
}
AGG = (
    "count(*) AS n, sum(t.net_pnl) AS net, "
    "sum(CASE WHEN t.net_pnl > 0 THEN 1 ELSE 0 END) AS wins, avg(t.r_multiple) AS avg_r"
)


def _lit(ids: Sequence[str]) -> str:
    for i in ids:
        if not all(c in "0123456789abcdef-" for c in i):
            raise ValueError("account id must be a lowercase uuid")  # no injection via ids
    return ", ".join(f"'{i}'" for i in ids)


def scoped_from(granted: Sequence[str], requested: Sequence[str] | None = None) -> str:
    """Mandatory scope subquery; ``requested`` narrows but can never exceed ``granted``."""
    allowed = list(granted) if requested is None else [a for a in requested if a in set(granted)]
    if not allowed:
        return "(SELECT * FROM journal_trades WHERE false)"
    return f"(SELECT * FROM journal_trades WHERE exchange_account_id::text IN ({_lit(allowed)}))"


def totals(src: str) -> str:
    return f"SELECT {AGG} FROM {src} t"


def breakdown(src: str, key: str) -> str:
    return f"SELECT {BREAKDOWNS[key]} AS k, {AGG} FROM {src} t GROUP BY 1"


def tag_breakdown(src: str) -> str:
    return (
        f"SELECT tt.journal_tag_id::text AS k, {AGG} FROM {src} t "
        "JOIN journal_trade_tags tt ON tt.journal_trade_id = t.id GROUP BY 1"
    )


def all_breakdowns(src: str) -> list[str]:
    return [totals(src), *(breakdown(src, k) for k in BREAKDOWNS), tag_breakdown(src)]


def equity_trade(src: str) -> str:
    return (
        "SELECT t.closed_at, sum(t.net_pnl) OVER (ORDER BY t.closed_at, t.id) AS equity "
        f"FROM {src} t ORDER BY t.closed_at, t.id"
    )


def mae_mfe(src: str) -> str:
    return f"SELECT t.mae_r, t.mfe_r, t.r_multiple FROM {src} t"


def filtered(src: str, account: str, symbol: str, tag: str, since: str, until: str) -> str:
    return (
        f"SELECT {AGG} FROM {src} t JOIN journal_trade_tags tt ON tt.journal_trade_id = t.id "
        f"WHERE t.symbol = '{symbol}' AND tt.journal_tag_id::text = '{tag}' "
        f"AND t.exchange_account_id::text = '{account}' "
        f"AND t.opened_at >= '{since}' AND t.opened_at < '{until}'"
    )
