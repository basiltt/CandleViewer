# E16-K01 (Spike S6) — storage measurement from the recorded corpus

Status: **in-process measurement done; live 7-day QuestDB run pending** (owner exception #1778 group A
waives the live leg for the agent phase; precedent E07-Q03 / #274 for QuestDB 16 MiB page quantisation).
Reproduce: `cd services/api && PYTHONPATH=. python bench/storage_measure.py --out-dir <dir>`
(`bench/storage_measure.py`; unit test `tests/unit/journal_bench/test_storage_measure.py`).

## 1. What was and was not measured

| Leg                                                                               | Done?               | How                                                                                                                                                                                                                                             |
| --------------------------------------------------------------------------------- | ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Bytes per row, ILP wire                                                           | yes (real)          | `serialize_ilp_line` from `storage/questdb/ilp_writer.py` over corpus-derived rows                                                                                                                                                              |
| Bytes per row, QuestDB on disk                                                    | **modelled**        | column widths from `backend/db/questdb/0001_core_tables.sql` (TIMESTAMP/DOUBLE/LONG 8 B, INT 4, BOOLEAN 1, SYMBOL 4 B id, STRING 12 B + 2 B/char). Not read from a QuestDB. Page quantisation (#274) and the SYMBOL dictionary are not modelled |
| Parquet cold size, hot/cold ratio                                                 | yes (real)          | corpus rows written with the E07 `MARKET_DATA_PROFILE` (zstd 6, v2.6, dictionary on symbol/side/action/tick_dir) via `write_parquet_file`; file size on disk                                                                                    |
| Wire bytes/day per stream                                                         | yes, but see caveat | frame bytes / observed window x 86 400                                                                                                                                                                                                          |
| 7 consecutive live days, hourly `tables()` disk sampling, p95 hourly, gap minutes | **no**              | needs docker/QuestDB and live capture (waived, #1778 A)                                                                                                                                                                                         |

**Critical caveat.** The corpus (`packages/fixtures/bybit/2026-10-05/`) is _documented-shape_, not a live capture
(manifest `source`). Its frame rates are synthetic: BTC trades arrive about every 30 s (4.3 k rows/day vs ~2.5 M real),
the book at 2 s frames with ~5 levels/delta (real: 100 ms, per §11.1 ~190 M level-rows/day at depth 200).
**Extrapolating its wire rate to 24 h therefore under-reports by 2-3 orders of magnitude** (e.g. 0.011 GB/day of book
wire vs a real 1+ GB/day) and is reported only as a column, never as a recommendation input. Row _shape_ (bytes per row)
is trustworthy; row _rate_ comes from `21-database-schema.md` §11.1 reference rates until a live run replaces them.
No gap > 10 min exists in the corpus windows (the documented seq-gap/reconnect fixtures are 1-15 s); no gap time was subtracted.

## 2. Bytes per row (measured / modelled)

| table               | depth | ILP B/row | hot B/row (model) | Parquet B/row | hot/cold | §11.1 hot / cold B/row |
| ------------------- | ----- | --------: | ----------------: | ------------: | -------: | ---------------------- |
| trades (BTC)        | -     |       214 |               145 |          23.6 |      6.1 | 64 / ~11               |
| trades (ETH)        | -     |       215 |               145 |          24.3 |      6.0 | 64 / ~11               |
| orderbook_deltas    | 200   |       183 |                72 |           6.0 |     11.9 | 56 / ~3.3              |
| orderbook_deltas    | 50    |       182 |                72 |           9.3 |      7.7 | 56 / ~3.3              |
| orderbook_snapshots | 200   |     8 770 |            14 477 |         2 859 |      5.1 | ~12 KB                 |
| orderbook_snapshots | 50    |     2 706 |             4 292 |         1 807 |      2.4 | -                      |
| tickers             | -     |       434 |               156 |          17.6 |      8.9 | 144 / ~16              |

Findings: (i) `trades` is ~2.3x the doc figure because `trade_id` is a 36-char UUID STRING (84 B modelled); real Bybit ids are
also 36 chars, so §11.1's 64 B is low. (ii) deltas hot 72 B (§11.1 said 56 B: 3 timestamp-like + 3 LONG + INT + 2 DOUBLE + 3 SYMBOL).
(iii) ILP bytes are text and are _wire_ cost, not disk cost. (iv) Parquet B/row for small files includes footer/dictionary overhead (542-26 k rows);
depth-50 is higher per row purely from fewer rows. Cold rows from a 3 h synthetic book (random sizes, tight price band) may compress
better or worse than real flow: treat cold as +/-2x.

## 3. GB/day per (symbol, stream, depth) — provisional

Rows/day from §11.1 (BTCUSDT-class; depth 50 = 1/4 of delta rows per §11.1), bytes/row from §2. ETHUSDT assumed equal to BTCUSDT
(no 3 h ETH book capture exists; ETH is the same order of magnitude in volume terms, unverified).

| stream                                                                |            rows/day |                                       hot GB/day (d200) |        cold GB/day (d200) |         hot GB/day (d50) |         cold GB/day (d50) |
| --------------------------------------------------------------------- | ------------------: | ------------------------------------------------------: | ------------------------: | -----------------------: | ------------------------: |
| trades                                                                |               2.5 M |                                                   0.362 |                     0.059 |                    0.362 |                     0.059 |
| orderbook_deltas                                                      | 190 M (d50: 47.5 M) |                                                   13.68 |                      1.14 |                     3.42 |                      0.44 |
| orderbook_snapshots                                                   |               1.5 k |                                                   0.022 |                     0.004 |                    0.006 |                     0.003 |
| tickers                                                               |               864 k |                                                   0.135 |                     0.015 |                    0.135 |                     0.015 |
| liquidations/OI/funding/klines                                        |               small |                                                   <0.01 |                     <0.01 |                    <0.01 |                     <0.01 |
| **raw total / symbol** (ETH rows: assumed = BTC, no ETH book capture) |                     |                                               **~14.2** |                 **~1.22** |                 **~3.9** |                 **~0.52** |
| **ETH raw total / symbol**                                            |                     |          **~14.2 (assumed = BTC, no ETH book capture)** | **~1.22 (assumed = BTC)** | **~3.9 (assumed = BTC)** | **~0.52 (assumed = BTC)** |
| derived (`bars_*`, `footprint_cells`, `heatmap_cells`)                |   not measured here | recomputable from `trades`; §11.1 estimates +2.3 GB hot |                           |                          |                           |

Error bars: rate x bytes/row, each +/-2x => **cold d200 0.6-2.4 GB/day/symbol**. Central 1.22 is ~1.6x the 0.75 planning
bound but below the 1.5 GB/day trigger of the ticket's third scenario, and that trigger is defined on the _live_ measurement, so no
follow-up is raised yet; E16-T06/T07 owners should treat 1.22-2.4 as the plausible cold range. Hot is dominated (96 %) by `orderbook_deltas`.

## 4. Peak vs quiet

Corpus 10-minute buckets: wire peak/quiet = 1.1 (book), 1.2-1.3 (trades), 1.0 (tickers burst, 60 s only). The generator is stationary, so this says
**nothing** about liquidation cascades. Until the live run provides hourly p95, size for the 5x burst already used by the §3.2 stress scenario of
`06-performance-and-load-standard.md` (a 5x burst for 60 s is bytes-negligible per day; the p95 _hourly_ ratio for disk is expected 2-3x — hypothesis, not measured).

## 5. Recommended defaults (hand-off to E16-T06 / E16-T07; code constants NOT changed here)

Sizing basis: 2 symbols (BTC+ETH), depth 200, QuestDB overhead +25 % (WAL, page quantisation, derived tables), **2x safety margin** on the cold figure.

| key                          | recommended                                                                           | derivation                                                                                                                                                                                                                            |
| ---------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `CV_RECORDER_HOT_DAYS`       | **7 (keep)**; **3 if depth 200 on >=3 symbols**                                       | 2 sym x 14.2 x 7 d = 199 GB x 1.25 = ~250 GB. 5 symbols = ~620 GB > cap, so use depth 50 (3.9 GB/day: 5 x 3.9 x 7 x 1.25 = 171 GB) or 3 hot days (266 GB)                                                                             |
| `CV_RECORDER_RETENTION_DAYS` | **30 (keep)**                                                                         | cold 2 sym x 1.22 x 30 = 73 GB central; 146 GB at the 2x error-bar top; 292 GB if the 2x safety margin is stacked on that                                                                                                             |
| `CV_DISK_CAP_GB`             | **600** for <=2 symbols at d200 (ADR default 500 is enough only for the central case) | 250 hot + 73 cold = ~320 GB central; 250 + 146 = ~400 GB at the error-bar top (hits the 80 % alert of a 500 cap); 250 + 292 = 542 GB with the stacked margin, hence 600. For larger sets raise the cap or cut depth/hot days as above |

**Gate:** E16-T06/E16-T07 MUST treat the recommended constants as provisional; do not bake them as final defaults until the live 7-day re-measure (#1778 A) lands; the plausible range runs to 2.4 GB/day (1.6x-3.2x budget #12). The margin per ADR-0015 is carried by the 600 GB cap, which stacks a 2x safety margin on top of the +/-2x error-bar top (conservative).

Re-validate all three after the live run; the number most likely to move is the d200 delta row rate (real vs §11.1).

## 6. Re-run on real QuestDB (staging / PRR checklist)

- [ ] 2 symbols x depth {50, 200}, >=7 days, E08 ingestion -> E07 tier wiring; record gap minutes (>10 min gaps subtracted from the denominator).
- [ ] Sample `SELECT table_name, diskSize FROM tables()` hourly into CSV (never `du`); mean and p95 hourly; set `cairo.writer.data.append.page.size` small (#274) or use >=24 h so 16 MiB quantisation washes out.
- [ ] Count rows/day per table to replace the §11.1 rate column; compare B/row to section 2 (model error).
- [ ] Run the manual roll-off with the real exporter; compare Parquet B/row and ratio to section 2.
- [ ] Emit `recorder_bytes_written_total{symbol,stream}` (E16-T03 name) from the harness.
- [ ] Replace this note's provisional figures, update ADR-0015 Validation and budget #12, tag the Architect if d200 BTC cold > 1.5 GB/day.
