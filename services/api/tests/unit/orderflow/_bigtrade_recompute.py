"""Independent DuckDB recomputation of big-trade output (E22-T04). Imports NO engine code.

Deliberately a different shape from the streaming engine: flagged prints are a `WHERE` over a
DECIMAL product; clusters are a recursive CTE over `(side, price_bucket)` partitions ordered by
`(ts, id)` that propagates the cluster start forward (island logic), instead of an ordered
open-cluster map with a deadline sweep. Spec: 24-internal-schemas §2.10 "Cluster key"."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

PRICE_SCALE = 10**8  # 8 price decimals: tick_size * PRICE_SCALE must be an integer >= 1

_LOAD = """
CREATE TABLE prints AS
SELECT trade_id, ts_event_us AS ts, side,
       CAST(price AS DECIMAL(18,8)) AS price, CAST(qty AS DECIMAL(18,8)) AS qty,
       CAST(price AS DECIMAL(38,8)) * CAST(qty AS DECIMAL(38,8)) AS notional,
       CAST(CAST(price AS DECIMAL(38,8)) * ? AS BIGINT) // ? AS ticks
FROM read_csv(?, header = true, delim = ',',
              columns = {'trade_id': 'VARCHAR', 'ts_event_us': 'BIGINT', 'side': 'VARCHAR',
                         'price': 'VARCHAR', 'qty': 'VARCHAR', 'is_block_trade': 'INTEGER'})
"""
# Prices load as DECIMAL(18,8); PRICE_SCALE is the single scale used for the load, the multiply and
# the tick conversion, so ticks = floor(price * SCALE / (tick * SCALE)) in exact integer arithmetic.

_CLUSTERS = """
WITH RECURSIVE keyed AS (
  SELECT trade_id, ts, side, qty, notional,
         ticks // ? AS bucket,
         row_number() OVER (PARTITION BY side, ticks // ? ORDER BY ts, trade_id) AS n
  FROM prints
), chain AS (
  SELECT side, bucket, n, trade_id, ts, qty, notional, ts AS start_ts
  FROM keyed WHERE n = 1
  UNION ALL
  SELECT k.side, k.bucket, k.n, k.trade_id, k.ts, k.qty, k.notional,
         CASE WHEN k.ts <= c.start_ts + CAST(? AS BIGINT) * 1000 THEN c.start_ts ELSE k.ts END
  FROM chain c JOIN keyed k
    ON k.side = c.side AND k.bucket = c.bucket AND k.n = c.n + 1
)
SELECT side, bucket, start_ts,
       min(ts) AS first_ts, max(ts) AS last_ts, count(*) AS cnt,
       arg_min(trade_id, n) AS first_id, arg_max(trade_id, n) AS last_id,
       sum(qty) AS total_qty, sum(notional) AS total_notional, max(qty) AS max_qty,
       list(trade_id ORDER BY n) AS ids
FROM chain GROUP BY side, bucket, start_ts
ORDER BY first_ts, first_id
"""


class Recompute:
    def __init__(self, trades_csv_gz: Path, tick_size: Decimal) -> None:
        """`tick_size * PRICE_SCALE` (1e8) must be an integer >= 1, i.e. at most 8 decimals."""
        scaled = tick_size * PRICE_SCALE
        if scaled < 1 or scaled != scaled.to_integral_value():
            raise ValueError(f"tick_size must be a multiple of 1e-8 and >= 1e-8, got {tick_size}")
        self.con = duckdb.connect(":memory:")
        self.con.execute(_LOAD, [PRICE_SCALE, int(scaled), trades_csv_gz.as_posix()])

    def flagged_notional(self, threshold: str) -> list[dict[str, Any]]:
        rows = self.con.execute(
            "SELECT trade_id, ts, side, CAST(price AS VARCHAR), CAST(qty AS VARCHAR), "
            "CAST(notional AS VARCHAR) FROM prints "
            "WHERE notional >= CAST(? AS DECIMAL(38,8)) ORDER BY ts, trade_id",
            [threshold],
        ).fetchall()
        return [
            {"trade_id": r[0], "ts": r[1], "side": r[2], "price": r[3], "qty": r[4],
             "notional": r[5]}
            for r in rows
        ]  # fmt: skip

    def trailing_rank(self, ts: int, window_ms: int, threshold: str) -> tuple[int, float]:
        """(window size, exact fraction of window notionals strictly below `threshold`)."""
        n, below = self.con.execute(
            "SELECT count(*), count(*) FILTER (WHERE notional < CAST(? AS DECIMAL(38,8))) "
            "FROM prints WHERE ts > ? - CAST(? AS BIGINT) * 1000 AND ts <= ?",
            [threshold, ts, window_ms, ts],
        ).fetchone() or (0, 0)
        return int(n), (below / n if n else 0.0)

    def clusters(self, tick_tolerance: int, window_ms: int) -> list[dict[str, Any]]:
        width = max(1, tick_tolerance)  # bucket = floor(price / (tick * width)) = ticks // width
        rows = self.con.execute(_CLUSTERS, [width, width, window_ms]).fetchall()
        return [
            {
                "side": r[0], "price_bucket": r[1], "first_ts_event": r[3],
                "last_ts_event": r[4], "trade_id_count": r[5], "first_trade_id": r[6],
                "last_trade_id": r[7], "total_qty": r[8], "total_notional": r[9],
                "max_print_qty": r[10], "trade_ids": list(r[11]),
            }
            for r in rows
        ]  # fmt: skip
