# Bar conformance bank (E12-Q02)

Five named tapes, each a **synthetic, deterministic** stand-in (exception #1778 A): real Bybit
symbol-day recordings do not exist yet (recorder E16, epic #42 comment 6095472425). They are
generated from the E12-T04 seeded generator (`services/api/bench/bar_determinism/tapes.py`) and
**must be replaced by recorder captures** when E16 ships. `MANIFEST.toml` records, per tape: source
symbol-day, print count, sha256, `synthetic = true`, licence note (public market-data shape only;
no account, order id, key or UID).

| Tape | Characteristic | Prints |
|---|---|---|
| `btcusdt-2026-09-01` | dense day (real day ~1.2M; **capped at 200k** for repo size) | 200 000 |
| `btcusdt-2026-09-02-gap` | 150-print WS sequence gap, 80 recovered by late backfill | 39 930 |
| `ethusdt-2026-09-03-thin` | thin tape, most 1 m intervals empty | 3 000 |
| `newlist-2026-09-04` | listed 11:17Z, `recording_started_at` 11:17Z | 20 000 |
| `edge-ticks` | exact-threshold / exact-range / exact-brick / boundary prints | 1 268 |

Tapes: `tapes/<name>.jsonl.gz` (gzip, one `{ts,price,size,side,trade_id}` per line, Decimal strings).
Goldens: `goldens/<tape>/<pair>.jsonl`, one canonical bar row per line, produced by the script, never
typed. Matrix: `time:1 time:5 time:1d tick:100 tick:1000 vol:50 range:20 delta:500 renko:30`;
`renko:atr:14` is a recorded 422 `BarSpecError` (ADR-0033 defers ATR) and `heikin_ashi:5` is
"not shipped" (Heikin-Ashi is a chart transform over time bars, not a builder).

## Updating goldens (human review required)

```
make golden-update                                  # dry run: diff summary, exit 1 if anything differs
make golden-update WRITE=1 REASON="why it changed"  # writes
```

Refused under `CI`, without a reason, and when a builder kind's output changed without a
`BUILD_VERSIONS` bump (`candleviewer/bars/rows.py`). Commit the regenerated files with the bump and
review `git diff --stat`. Tests: `services/api/tests/unit/bars/test_conformance_*.py`; the dense and
gap tapes plus the full-day chunk-equivalence run are `harness`-marked (nightly `-m harness`).
