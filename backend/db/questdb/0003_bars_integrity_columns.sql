-- QuestDB hot-tier DDL, batch 3 (E12-T02, #345).
-- Integrity columns for the bars_* family requested by the E12-X01 STRIDE model on #345:
--   source        SYMBOL  'tape' | 'kline' | 'parquet' (SR-E12-10: provenance of the row)
--   row_checksum  LONG    63-bit sha256 prefix over the row's values, verified on read (SR-E12-11)
-- Additive only (C-5.1); the six tables themselves are 0002 (21-database-schema.md Sec.4.8).

ALTER TABLE bars_time ADD COLUMN IF NOT EXISTS source SYMBOL CAPACITY 8 CACHE;
ALTER TABLE bars_time ADD COLUMN IF NOT EXISTS row_checksum LONG;
ALTER TABLE bars_tick ADD COLUMN IF NOT EXISTS source SYMBOL CAPACITY 8 CACHE;
ALTER TABLE bars_tick ADD COLUMN IF NOT EXISTS row_checksum LONG;
ALTER TABLE bars_volume ADD COLUMN IF NOT EXISTS source SYMBOL CAPACITY 8 CACHE;
ALTER TABLE bars_volume ADD COLUMN IF NOT EXISTS row_checksum LONG;
ALTER TABLE bars_range ADD COLUMN IF NOT EXISTS source SYMBOL CAPACITY 8 CACHE;
ALTER TABLE bars_range ADD COLUMN IF NOT EXISTS row_checksum LONG;
ALTER TABLE bars_renko ADD COLUMN IF NOT EXISTS source SYMBOL CAPACITY 8 CACHE;
ALTER TABLE bars_renko ADD COLUMN IF NOT EXISTS row_checksum LONG;
ALTER TABLE bars_delta ADD COLUMN IF NOT EXISTS source SYMBOL CAPACITY 8 CACHE;
ALTER TABLE bars_delta ADD COLUMN IF NOT EXISTS row_checksum LONG;
