-- QuestDB hot-tier DDL, batch 3 (E12-T02, #345).
-- Integrity columns for the bars_* family requested by the E12-X01 STRIDE model on #345:
--   source        SYMBOL  'tape' | 'kline' | 'parquet' (SR-E12-10: provenance of the row)
--   row_checksum  LONG    63-bit sha256 prefix over the row's values, verified on read (SR-E12-11)
-- Additive only (C-5.1); no IF NOT EXISTS (the CI QuestDB rejects it: "invalid type"); idempotency is the _cv_migrations record; the six tables themselves are 0002 (21-database-schema.md Sec.4.8).

ALTER TABLE bars_time ADD COLUMN source SYMBOL CAPACITY 8 CACHE;
ALTER TABLE bars_time ADD COLUMN row_checksum LONG;
ALTER TABLE bars_tick ADD COLUMN source SYMBOL CAPACITY 8 CACHE;
ALTER TABLE bars_tick ADD COLUMN row_checksum LONG;
ALTER TABLE bars_volume ADD COLUMN source SYMBOL CAPACITY 8 CACHE;
ALTER TABLE bars_volume ADD COLUMN row_checksum LONG;
ALTER TABLE bars_range ADD COLUMN source SYMBOL CAPACITY 8 CACHE;
ALTER TABLE bars_range ADD COLUMN row_checksum LONG;
ALTER TABLE bars_renko ADD COLUMN source SYMBOL CAPACITY 8 CACHE;
ALTER TABLE bars_renko ADD COLUMN row_checksum LONG;
ALTER TABLE bars_delta ADD COLUMN source SYMBOL CAPACITY 8 CACHE;
ALTER TABLE bars_delta ADD COLUMN row_checksum LONG;
