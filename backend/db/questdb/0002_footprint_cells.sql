-- QuestDB hot-tier DDL, batch 2 of 2 (E07-T03).
-- Transcribed verbatim from docs/plan/21-database-schema.md Sec.4.8-4.13
-- (bars_* family, footprint_cells, profiles, orderflow_metrics,
-- heatmap_cells, engine_metrics). Do not hand-edit a column without
-- updating that doc in the same PR (Sec.13.2 "Change control").

CREATE TABLE IF NOT EXISTS bars_time (
  ts              TIMESTAMP,      -- bar open
  close_ts        TIMESTAMP,
  symbol          SYMBOL CAPACITY 256 CACHE,
  bar_param       SYMBOL CAPACITY 64 CACHE,   -- '1m','5m','15m','1h','4h','1d'
  open            DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
  volume          DOUBLE,
  buy_volume      DOUBLE,
  sell_volume     DOUBLE,
  delta           DOUBLE,
  cum_delta       DOUBLE,
  max_delta       DOUBLE,
  min_delta       DOUBLE,
  delta_pct       DOUBLE,
  trade_count     LONG,
  buy_trade_count LONG,
  sell_trade_count LONG,
  vwap            DOUBLE,
  poc_price       DOUBLE,         -- point of control within the bar
  value_area_high DOUBLE,
  value_area_low  DOUBLE,
  imbalance_count INT,            -- stacked diagonal imbalances in this bar
  is_closed       BOOLEAN,
  build_version   INT             -- bumped when the builder algorithm changes -> triggers rebuild
) TIMESTAMP(ts) PARTITION BY MONTH WAL
  DEDUP UPSERT KEYS(ts, symbol, bar_param);

CREATE TABLE IF NOT EXISTS bars_tick (
  ts              TIMESTAMP,
  close_ts        TIMESTAMP,
  symbol          SYMBOL CAPACITY 256 CACHE,
  bar_param       SYMBOL CAPACITY 64 CACHE,
  open            DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
  volume          DOUBLE,
  buy_volume      DOUBLE,
  sell_volume     DOUBLE,
  delta           DOUBLE,
  cum_delta       DOUBLE,
  max_delta       DOUBLE,
  min_delta       DOUBLE,
  delta_pct       DOUBLE,
  trade_count     LONG,
  buy_trade_count LONG,
  sell_trade_count LONG,
  vwap            DOUBLE,
  poc_price       DOUBLE,
  value_area_high DOUBLE,
  value_area_low  DOUBLE,
  imbalance_count INT,
  is_closed       BOOLEAN,
  build_version   INT
) TIMESTAMP(ts) PARTITION BY MONTH WAL
  DEDUP UPSERT KEYS(ts, symbol, bar_param);

CREATE TABLE IF NOT EXISTS bars_range (
  ts              TIMESTAMP,
  close_ts        TIMESTAMP,
  symbol          SYMBOL CAPACITY 256 CACHE,
  bar_param       SYMBOL CAPACITY 64 CACHE,
  open            DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
  volume          DOUBLE,
  buy_volume      DOUBLE,
  sell_volume     DOUBLE,
  delta           DOUBLE,
  cum_delta       DOUBLE,
  max_delta       DOUBLE,
  min_delta       DOUBLE,
  delta_pct       DOUBLE,
  trade_count     LONG,
  buy_trade_count LONG,
  sell_trade_count LONG,
  vwap            DOUBLE,
  poc_price       DOUBLE,
  value_area_high DOUBLE,
  value_area_low  DOUBLE,
  imbalance_count INT,
  is_closed       BOOLEAN,
  build_version   INT,
  open_source_ts  TIMESTAMP       -- timestamp of the trade that opened the brick (not time-aligned)
) TIMESTAMP(ts) PARTITION BY MONTH WAL
  DEDUP UPSERT KEYS(ts, symbol, bar_param);

CREATE TABLE IF NOT EXISTS bars_renko (
  ts              TIMESTAMP,
  close_ts        TIMESTAMP,
  symbol          SYMBOL CAPACITY 256 CACHE,
  bar_param       SYMBOL CAPACITY 64 CACHE,
  open            DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
  volume          DOUBLE,
  buy_volume      DOUBLE,
  sell_volume     DOUBLE,
  delta           DOUBLE,
  cum_delta       DOUBLE,
  max_delta       DOUBLE,
  min_delta       DOUBLE,
  delta_pct       DOUBLE,
  trade_count     LONG,
  buy_trade_count LONG,
  sell_trade_count LONG,
  vwap            DOUBLE,
  poc_price       DOUBLE,
  value_area_high DOUBLE,
  value_area_low  DOUBLE,
  imbalance_count INT,
  is_closed       BOOLEAN,
  build_version   INT,
  open_source_ts  TIMESTAMP       -- timestamp of the trade that opened the brick (not time-aligned)
) TIMESTAMP(ts) PARTITION BY MONTH WAL
  DEDUP UPSERT KEYS(ts, symbol, bar_param);

CREATE TABLE IF NOT EXISTS bars_delta (
  ts              TIMESTAMP,
  close_ts        TIMESTAMP,
  symbol          SYMBOL CAPACITY 256 CACHE,
  bar_param       SYMBOL CAPACITY 64 CACHE,
  open            DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
  volume          DOUBLE,
  buy_volume      DOUBLE,
  sell_volume     DOUBLE,
  delta           DOUBLE,
  cum_delta       DOUBLE,
  max_delta       DOUBLE,
  min_delta       DOUBLE,
  delta_pct       DOUBLE,
  trade_count     LONG,
  buy_trade_count LONG,
  sell_trade_count LONG,
  vwap            DOUBLE,
  poc_price       DOUBLE,
  value_area_high DOUBLE,
  value_area_low  DOUBLE,
  imbalance_count INT,
  is_closed       BOOLEAN,
  build_version   INT
) TIMESTAMP(ts) PARTITION BY MONTH WAL
  DEDUP UPSERT KEYS(ts, symbol, bar_param);

CREATE TABLE IF NOT EXISTS bars_volume (
  ts              TIMESTAMP,
  close_ts        TIMESTAMP,
  symbol          SYMBOL CAPACITY 256 CACHE,
  bar_param       SYMBOL CAPACITY 64 CACHE,
  open            DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
  volume          DOUBLE,
  buy_volume      DOUBLE,
  sell_volume     DOUBLE,
  delta           DOUBLE,
  cum_delta       DOUBLE,
  max_delta       DOUBLE,
  min_delta       DOUBLE,
  delta_pct       DOUBLE,
  trade_count     LONG,
  buy_trade_count LONG,
  sell_trade_count LONG,
  vwap            DOUBLE,
  poc_price       DOUBLE,
  value_area_high DOUBLE,
  value_area_low  DOUBLE,
  imbalance_count INT,
  is_closed       BOOLEAN,
  build_version   INT
) TIMESTAMP(ts) PARTITION BY MONTH WAL
  DEDUP UPSERT KEYS(ts, symbol, bar_param);

CREATE TABLE IF NOT EXISTS footprint_cells (
  ts              TIMESTAMP,      -- bar open ts (matches bars_* ts)
  symbol          SYMBOL CAPACITY 256 CACHE,
  bar_family      SYMBOL CAPACITY 16 CACHE,   -- 'time' | 'tick' | 'volume' | 'range' | 'renko' | 'delta'
  bar_param       SYMBOL CAPACITY 64 CACHE,
  price           DOUBLE,
  bid_volume      DOUBLE,         -- traded at bid (sell aggressor)
  ask_volume      DOUBLE,         -- traded at ask (buy aggressor)
  total_volume    DOUBLE,
  delta           DOUBLE,
  trade_count     LONG,
  buy_trade_count LONG,
  sell_trade_count LONG,
  max_trade_size  DOUBLE,
  imbalance_flag  SYMBOL CAPACITY 8 CACHE,   -- 'none' | 'bid' | 'ask'
  imbalance_ratio DOUBLE,         -- diagonal ratio; default threshold 300%
  is_poc          BOOLEAN,
  is_va           BOOLEAN,
  build_version   INT
) TIMESTAMP(ts) PARTITION BY DAY WAL
  DEDUP UPSERT KEYS(ts, symbol, bar_family, bar_param, price);

CREATE TABLE IF NOT EXISTS profiles (
  ts            TIMESTAMP,        -- profile period start
  end_ts        TIMESTAMP,
  symbol        SYMBOL CAPACITY 256 CACHE,
  profile_kind  SYMBOL CAPACITY 16 CACHE,   -- 'volume' | 'delta' | 'tpo'
  period_kind   SYMBOL CAPACITY 16 CACHE,   -- 'session' | 'composite' | 'visible' | 'swing' | 'custom'
  period_ref    STRING,           -- e.g. '2026-09-14' or a swing id
  price         DOUBLE,
  row_size      DOUBLE,           -- price bucket height
  volume        DOUBLE,
  bid_volume    DOUBLE,
  ask_volume    DOUBLE,
  delta         DOUBLE,
  tpo_count     INT,
  is_poc        BOOLEAN,
  is_vah        BOOLEAN,
  is_val        BOOLEAN,
  is_single_print BOOLEAN,
  value_area_pct DOUBLE,          -- 70 default
  build_version INT
) TIMESTAMP(ts) PARTITION BY MONTH WAL
  DEDUP UPSERT KEYS(ts, symbol, profile_kind, period_kind, period_ref, price);

CREATE TABLE IF NOT EXISTS orderflow_metrics (
  ts                TIMESTAMP,
  symbol            SYMBOL CAPACITY 256 CACHE,
  cvd               DOUBLE,
  cvd_session       DOUBLE,
  delta_1s          DOUBLE,
  trades_per_sec    DOUBLE,
  notional_per_sec  DOUBLE,
  buy_ratio         DOUBLE,
  book_imbalance    DOUBLE,       -- (bidQty-askQty)/(bidQty+askQty) top-N
  book_thickness    DOUBLE,
  spread_ticks      DOUBLE,
  realized_vol_1m   DOUBLE,
  atr_14            DOUBLE,
  regime            SYMBOL CAPACITY 16 CACHE,   -- 'trend_up'|'trend_down'|'range'|'volatile'|'calm'
  regime_confidence DOUBLE,
  stacked_imbalance_up   INT,
  stacked_imbalance_down INT,
  iceberg_score     DOUBLE,       -- ESTIMATED (heuristic, no L3 feed)
  stoprun_score     DOUBLE,       -- ESTIMATED
  absorption_score  DOUBLE        -- ESTIMATED
) TIMESTAMP(ts) PARTITION BY DAY WAL
  DEDUP UPSERT KEYS(ts, symbol);

CREATE TABLE IF NOT EXISTS heatmap_cells (
  ts          TIMESTAMP,          -- 100 ms bucket
  symbol      SYMBOL CAPACITY 256 CACHE,
  price       DOUBLE,
  bid_size    DOUBLE,
  ask_size    DOUBLE,
  bid_age_ms  LONG,               -- how long this level has rested (iceberg/refresh heuristics)
  ask_age_ms  LONG,
  refill_count INT
) TIMESTAMP(ts) PARTITION BY HOUR WAL
  DEDUP UPSERT KEYS(ts, symbol, price);

CREATE TABLE IF NOT EXISTS engine_metrics (
  ts             TIMESTAMP,
  component      SYMBOL CAPACITY 32 CACHE,
  symbol         SYMBOL CAPACITY 256 CACHE,
  metric         SYMBOL CAPACITY 128 CACHE,   -- 'ingest_lag_ms','queue_depth','fps','ws_rtt_ms','drop_count'
  value          DOUBLE,
  labels         STRING
) TIMESTAMP(ts) PARTITION BY DAY WAL;
