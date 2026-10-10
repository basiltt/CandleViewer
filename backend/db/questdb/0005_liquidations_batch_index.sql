-- QuestDB hot-tier DDL, batch 5 (E16-T03, #406).
-- One allLiquidation message can carry several prints with the same side/price/size. The
-- 0001 key (ts, symbol, side, price, size) upserted them into ONE row, silently losing
-- prints on first write and on WAL replay, which breaks replayability (C-2.15). batch_index is
-- the print's position in its message (24-internal-schemas L6) and joins the key.
-- Additive: an existing row gets batch_index = NULL, and QuestDB treats NULL as a key value,
-- so the rows already stored keep their identity.

ALTER TABLE liquidations ADD COLUMN IF NOT EXISTS batch_index LONG;
ALTER TABLE liquidations DEDUP ENABLE UPSERT KEYS(ts, symbol, side, price, size, batch_index);
