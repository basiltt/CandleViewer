"""Single definition of each stream's natural (dedup) key (E07-T05).

Mirrors the `DEDUP UPSERT KEYS(...)` clause of the QuestDB DDL in
`backend/db/questdb/`; `test_natural_keys.py` asserts the two never drift.
The router's straddle merge dedups on exactly these columns.
"""

from __future__ import annotations

from candleviewer.storage.models import StreamKind

#: stream -> (QuestDB table, dedup key columns incl. the designated `ts`).
NATURAL_KEY_BY_TABLE: dict[str, tuple[str, ...]] = {
    "trades": ("ts", "symbol", "trade_id"),
    "orderbook_deltas": ("ts", "symbol", "depth", "side", "price", "update_id"),
    "orderbook_snapshots": ("ts", "symbol", "depth", "epoch_id"),
    "tickers": ("ts", "symbol"),
    "klines": ("ts", "symbol", "interval"),
    "liquidations": ("ts", "symbol", "side", "price", "size"),
    "open_interest": ("ts", "symbol", "interval", "source"),
    "funding_rates": ("ts", "symbol"),
}

TABLE_BY_STREAM: dict[StreamKind, str] = {
    StreamKind.TRADES: "trades",
    StreamKind.ORDERBOOK_DELTA: "orderbook_deltas",
    StreamKind.ORDERBOOK_SNAPSHOT: "orderbook_snapshots",
    StreamKind.TICKERS: "tickers",
    StreamKind.KLINES: "klines",
    StreamKind.LIQUIDATIONS: "liquidations",
    StreamKind.OPEN_INTEREST: "open_interest",
    StreamKind.FUNDING_RATES: "funding_rates",
}

NATURAL_KEY: dict[StreamKind, tuple[str, ...]] = {
    stream: NATURAL_KEY_BY_TABLE[table] for stream, table in TABLE_BY_STREAM.items()
}
