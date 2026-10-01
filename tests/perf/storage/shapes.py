"""Query shapes #1-#11 of 21-database-schema.md section 13.2 (DuckDB-proxy SQL).

`k01_id` links each shape to the E07-K01 (spikes/storage/bench.py) shape id so
numbers stay comparable with ADR-0022's table; a test asserts the mapping
covers exactly the K01 shape-id set.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueryShape:
    id: int
    name: str
    sql: str
    target_ms: float
    k01_id: str | None


SHAPES: tuple[QueryShape, ...] = (
    QueryShape(
        1,
        "chart bootstrap",
        "SELECT * FROM bars_time WHERE symbol='BTCUSDT' AND bar_param='1m' ORDER BY ts",
        100.0,
        "D",
    ),
    QueryShape(
        2,
        "footprint render",
        "SELECT * FROM footprint_cells WHERE symbol='BTCUSDT' AND ts BETWEEN {lo} AND {mid}",
        150.0,
        "A",
    ),
    QueryShape(
        3,
        "live bar building",
        "SELECT ts // 60000000 b, sum(qty) FROM trades "
        "WHERE symbol='BTCUSDT' AND ts > {mid} GROUP BY b",
        50.0,
        None,
    ),
    QueryShape(
        4,
        "big-trade bubbles",
        "SELECT * FROM trades WHERE symbol='BTCUSDT' AND notional > 500000 "
        "AND ts BETWEEN {lo} AND {hi}",
        80.0,
        "E",
    ),
    QueryShape(
        5,
        "last price",
        "SELECT * FROM tickers WHERE symbol='BTCUSDT' ORDER BY ts DESC LIMIT 1",
        10.0,
        "F",
    ),
    QueryShape(
        6,
        "DOM heatmap trail",
        "SELECT * FROM heatmap_cells WHERE symbol='BTCUSDT' AND ts > {recent}",
        50.0,
        None,
    ),
    QueryShape(
        7,
        "replay seek",
        "SELECT * FROM (SELECT * FROM orderbook_deltas WHERE symbol='BTCUSDT' "
        "AND ts <= {mid} ORDER BY ts DESC LIMIT 1) "
        "UNION ALL SELECT * FROM (SELECT * FROM orderbook_deltas "
        "WHERE symbol='BTCUSDT' AND ts > {mid} ORDER BY ts LIMIT 5000)",
        200.0,
        "B",
    ),
    QueryShape(
        8,
        "CVD pane",
        "SELECT ts // 60000000 b, sum(cvd_delta) FROM orderflow_metrics "
        "WHERE symbol='BTCUSDT' AND ts BETWEEN {lo} AND {hi} GROUP BY b",
        60.0,
        "C",
    ),
    QueryShape(
        9,
        "profile panel",
        "SELECT * FROM profiles WHERE symbol='BTCUSDT' AND profile_kind='volume' "
        "AND period_ref='d1'",
        40.0,
        None,
    ),
    QueryShape(
        10,
        "OI/funding panes",
        "SELECT * FROM open_interest WHERE symbol='BTCUSDT' AND ts BETWEEN {lo} AND {hi}",
        30.0,
        None,
    ),
    QueryShape(
        11,
        "trade/book alignment",
        "SELECT count(*) FROM trades t ASOF JOIN tickers k "
        "ON t.symbol=k.symbol AND t.ts >= k.ts WHERE t.symbol='BTCUSDT'",
        200.0,
        None,
    ),
)
