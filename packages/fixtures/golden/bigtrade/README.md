# Big-trade golden (E22-T04)

Files: `trades_BTCUSDT.csv.gz` (input prints), `expected_BTCUSDT.jsonl.gz` (every engine event
for the three configurations, canonical JSON), `summary.json` (`algo_version`, per-case counts and
sha256). Consumed by `services/api/tests/unit/orderflow/test_bigtrade_golden_parity.py`.

## Provenance (C-13.5)

Source: recorded corpus `bybit/2026-10-05/ws/clean_publicTrade_BTCUSDT.jsonl` (public live stream
shape, symbol BTCUSDT, no account data; already redacted), passed through the production parser and
re-serialised sorted by `(ts_event, trade_id)`: 542 prints, 2.99 h (1 699 999 999 995 us ..
1 700 010 769 995 us). **Deviation:** this is NOT a full symbol-day. It is the longest contiguous
recorded BTCUSDT trade window in the repo (the corpus was built per exception #1778 group A);
nothing was synthesised. Size: 5.2 kB trades + 71 kB expected, gzip.

Configurations: (1) notional 250 000, no clustering (flags nothing on this tape: the largest print
is ~31.6 k USDT; the empty set is itself the parity result, and a 30 000 cut proves the harness is
non-vacuous); (2) percentile 99 / 1 h; (3) notional 100 000, `cluster_window_ms=250`,
`cluster_tolerance_ticks=1`.

## Independent recompute

`tests/unit/orderflow/_bigtrade_recompute.py` (DuckDB SQL, no engine imports): `WHERE` over a
DECIMAL notional for flags, a recursive-CTE island query over `(side, price_bucket)` for clusters.
Percentile mode (P2 estimate, not exactly recomputable) is checked as flags == ASOF join of the
engine's emitted threshold schedule, plus a rank sanity bound.

## Regeneration (deliberate algorithm change only)

1. Bump `ALGO_VERSION` in `tests/unit/orderflow/_bigtrade_golden_lib.py` (the regen test refuses to
   run with the same version as `summary.json`).
2. `cd services/api && CV_REGEN_GOLDEN=1 PYTHONPATH=. pytest tests/unit/orderflow/test_bigtrade_golden_parity.py -k regenerate`
3. Review the diff of `summary.json`; the DuckDB parity tests must still pass unchanged (they are
   independent of the golden). Put a written rationale in the PR (03 §4.2) and get review per
   24-internal-schemas §13.6 (a bump triggers aggregate rebuild).
