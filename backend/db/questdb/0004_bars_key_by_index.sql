-- QuestDB hot-tier DDL, batch 4 (E12-T02 follow-up, #2016; parent #2014).
-- Re-keys the six bars_* tables by bar identity: DEDUP UPSERT KEYS(ts, symbol, bar_param,
-- generation, index) (21-database-schema.md Sec.4.8 / Sec.9.5). Non-time bars can share `ts`
-- (a 5000-qty print at threshold 1500 yields 3 bars), so (ts, symbol, bar_param) collapsed them.
--
-- OWNER DECISION (#1778 item R, 2026-10-09): PATH B - drop-and-recreate. No production data
-- exists, and bars_* is derived data rebuildable from `trades` (Sec.8), so DROP + CREATE loses
-- nothing of record. QuestDB cannot alter DEDUP keys in place. DESTRUCTIVE: do not run against
-- a populated install without a rebuild plan.
--
--   generation LONG  ADR-0033 series generation; the writer stamps 0 until ADR-0033 is ratified
--                    (QuestDB has no column DEFAULT).
--   "index"    LONG  Bar.index (24 Sec.3.1). Quoted because INDEX is a QuestDB reserved word.
-- The 0003 integrity columns (source, row_checksum) are part of the recreated tables.
-- DROP TABLE IF EXISTS keeps this idempotent on an empty install; the _cv_migrations record
-- makes the whole file run once.

DROP TABLE IF EXISTS bars_time;
CREATE TABLE IF NOT EXISTS bars_time (
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
  source          SYMBOL CAPACITY 8 CACHE,
  row_checksum    LONG,
  generation      LONG,
  "index"         LONG
) TIMESTAMP(ts) PARTITION BY MONTH WAL
  DEDUP UPSERT KEYS(ts, symbol, bar_param, generation, "index");

DROP TABLE IF EXISTS bars_tick;
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
  build_version   INT,
  source          SYMBOL CAPACITY 8 CACHE,
  row_checksum    LONG,
  generation      LONG,
  "index"         LONG
) TIMESTAMP(ts) PARTITION BY MONTH WAL
  DEDUP UPSERT KEYS(ts, symbol, bar_param, generation, "index");

DROP TABLE IF EXISTS bars_volume;
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
  build_version   INT,
  source          SYMBOL CAPACITY 8 CACHE,
  row_checksum    LONG,
  generation      LONG,
  "index"         LONG
) TIMESTAMP(ts) PARTITION BY MONTH WAL
  DEDUP UPSERT KEYS(ts, symbol, bar_param, generation, "index");

DROP TABLE IF EXISTS bars_range;
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
  open_source_ts  TIMESTAMP,
  source          SYMBOL CAPACITY 8 CACHE,
  row_checksum    LONG,
  generation      LONG,
  "index"         LONG
) TIMESTAMP(ts) PARTITION BY MONTH WAL
  DEDUP UPSERT KEYS(ts, symbol, bar_param, generation, "index");

DROP TABLE IF EXISTS bars_renko;
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
  open_source_ts  TIMESTAMP,
  source          SYMBOL CAPACITY 8 CACHE,
  row_checksum    LONG,
  generation      LONG,
  "index"         LONG
) TIMESTAMP(ts) PARTITION BY MONTH WAL
  DEDUP UPSERT KEYS(ts, symbol, bar_param, generation, "index");

DROP TABLE IF EXISTS bars_delta;
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
  build_version   INT,
  source          SYMBOL CAPACITY 8 CACHE,
  row_checksum    LONG,
  generation      LONG,
  "index"         LONG
) TIMESTAMP(ts) PARTITION BY MONTH WAL
  DEDUP UPSERT KEYS(ts, symbol, bar_param, generation, "index");

