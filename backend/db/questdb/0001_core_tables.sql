-- QuestDB hot-tier DDL, batch 1 of 2 (E07-T03).
-- Transcribed verbatim from docs/plan/21-database-schema.md Sec.4.1-4.7
-- (trades, orderbook_deltas, orderbook_snapshots, tickers, klines,
-- liquidations, open_interest, funding_rates). Do not hand-edit a column
-- without updating that doc in the same PR (Sec.13.2 "Change control").

CREATE TABLE IF NOT EXISTS trades (
  ts          TIMESTAMP,          -- Bybit T (ms -> us)
  recv_ts     TIMESTAMP,
  symbol      SYMBOL CAPACITY 256 CACHE,
  side        SYMBOL CAPACITY 4 CACHE,     -- 'Buy' | 'Sell' (taker/aggressor, given directly by Bybit)
  price       DOUBLE,
  size        DOUBLE,
  notional    DOUBLE,             -- price*size, precomputed for threshold scans
  trade_id    STRING,             -- Bybit i
  tick_dir    SYMBOL CAPACITY 8 CACHE,     -- PlusTick | ZeroPlusTick | MinusTick | ZeroMinusTick (L)
  is_block    BOOLEAN,            -- BT
  seq         LONG                -- monotone per-symbol ingest counter (gap detection)
) TIMESTAMP(ts) PARTITION BY DAY WAL
  DEDUP UPSERT KEYS(ts, symbol, trade_id);

CREATE TABLE IF NOT EXISTS orderbook_deltas (
  ts          TIMESTAMP,
  recv_ts     TIMESTAMP,
  symbol      SYMBOL CAPACITY 256 CACHE,
  depth       INT,                -- 1 | 50 | 200 | 500 (which topic produced it)
  side        SYMBOL CAPACITY 4 CACHE,   -- 'bid' | 'ask'
  price       DOUBLE,
  size        DOUBLE,             -- 0 = delete level
  action      SYMBOL CAPACITY 8 CACHE,   -- 'insert' | 'update' | 'delete'
  update_id   LONG,               -- Bybit u
  cross_seq   LONG,               -- Bybit seq
  epoch_id    LONG                -- increments on every snapshot rebuild
) TIMESTAMP(ts) PARTITION BY HOUR WAL
  DEDUP UPSERT KEYS(ts, symbol, depth, side, price, update_id);

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
  ts          TIMESTAMP,
  recv_ts     TIMESTAMP,
  symbol      SYMBOL CAPACITY 256 CACHE,
  depth       INT,
  epoch_id    LONG,
  update_id   LONG,
  cross_seq   LONG,
  source      SYMBOL CAPACITY 8 CACHE,   -- 'exchange' | 'synthetic'
  bids        STRING,            -- JSON array [[price,size],...] truncated to `depth`
  asks        STRING,
  level_count INT,
  checksum    LONG               -- CRC32 of the serialized book, validates delta application
) TIMESTAMP(ts) PARTITION BY DAY WAL
  DEDUP UPSERT KEYS(ts, symbol, depth, epoch_id);

CREATE TABLE IF NOT EXISTS tickers (
  ts               TIMESTAMP,
  recv_ts          TIMESTAMP,
  symbol           SYMBOL CAPACITY 256 CACHE,
  last_price       DOUBLE,
  mark_price       DOUBLE,
  index_price      DOUBLE,
  bid1_price       DOUBLE,
  bid1_size        DOUBLE,
  ask1_price       DOUBLE,
  ask1_size        DOUBLE,
  volume_24h       DOUBLE,
  turnover_24h     DOUBLE,
  price_24h_pcnt   DOUBLE,
  high_24h         DOUBLE,
  low_24h          DOUBLE,
  open_interest    DOUBLE,
  open_interest_value DOUBLE,
  funding_rate     DOUBLE,
  next_funding_ts  TIMESTAMP,
  basis            DOUBLE          -- mark - index, precomputed
) TIMESTAMP(ts) PARTITION BY DAY WAL
  DEDUP UPSERT KEYS(ts, symbol);

CREATE TABLE IF NOT EXISTS klines (
  ts         TIMESTAMP,           -- bar open time
  symbol     SYMBOL CAPACITY 256 CACHE,
  interval   SYMBOL CAPACITY 32 CACHE,   -- '1','3','5','15','30','60','240','D'
  open       DOUBLE,
  high       DOUBLE,
  low        DOUBLE,
  close      DOUBLE,
  volume     DOUBLE,
  turnover   DOUBLE,
  confirmed  BOOLEAN,
  source     SYMBOL CAPACITY 4 CACHE     -- 'ws' | 'rest'
) TIMESTAMP(ts) PARTITION BY MONTH WAL
  DEDUP UPSERT KEYS(ts, symbol, interval);

CREATE TABLE IF NOT EXISTS liquidations (
  ts        TIMESTAMP,
  recv_ts   TIMESTAMP,
  symbol    SYMBOL CAPACITY 256 CACHE,
  side      SYMBOL CAPACITY 4 CACHE,   -- side of the liquidated position's closing order
  price     DOUBLE,
  size      DOUBLE,
  notional  DOUBLE,
  stream    SYMBOL CAPACITY 8 CACHE    -- 'all' (allLiquidation, 1s aggregated) | 'legacy'
) TIMESTAMP(ts) PARTITION BY DAY WAL
  DEDUP UPSERT KEYS(ts, symbol, side, price, size);

CREATE TABLE IF NOT EXISTS open_interest (
  ts        TIMESTAMP,
  symbol    SYMBOL CAPACITY 256 CACHE,
  oi        DOUBLE,             -- contracts
  oi_value  DOUBLE,             -- USD notional
  interval  SYMBOL CAPACITY 8 CACHE,   -- '1s' (from tickers) | '5min' | '15min' | '1h' | '4h' | '1d' (REST backfill)
  source    SYMBOL CAPACITY 8 CACHE    -- 'ws_ticker' | 'rest'
) TIMESTAMP(ts) PARTITION BY MONTH WAL
  DEDUP UPSERT KEYS(ts, symbol, interval, source);

CREATE TABLE IF NOT EXISTS funding_rates (
  ts             TIMESTAMP,      -- funding settlement time
  symbol         SYMBOL CAPACITY 256 CACHE,
  funding_rate   DOUBLE,
  annualised_pct DOUBLE,         -- rate * periods_per_year * 100, precomputed
  interval_min   INT,            -- 480 for most USDT perps
  source         SYMBOL CAPACITY 8 CACHE
) TIMESTAMP(ts) PARTITION BY YEAR WAL
  DEDUP UPSERT KEYS(ts, symbol);
