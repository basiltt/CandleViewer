# @candleviewer/fixtures

Recorded, **redacted** Bybit fixtures + golden outputs, shared by the
TypeScript and Python test suites (CONSTITUTION.md C-13.5, `.claude/rules/40-testing.md`).

## Layout

- `raw/` — recorded WS/REST captures (redacted: no API keys, signatures,
  UIDs, or order ids tied to a real account).
- `golden/` — expected outputs (bar aggregation, footprint, decoders) for
  regression comparisons.
- `scripts/verify.mjs` — the redaction gate: fails if any file under `raw/`
  or `golden/` contains a credential-shaped string (API key, signature,
  `Authorization` header, PEM key block). Every new fixture must pass this
  before being committed (E02-X01 threat: "recorded fixture leaks credentials").

**No fixture in this package may originate from a live network call in a test
or CI run.** Fixtures are recorded via the (future) recorder tool and reviewed
before commit.

## Golden provenance (C-13.5)

- `golden/bars/time_bars_BTCUSDT.jsonl` — E12-S01 time bars (1m/5m/1h, one bar per line).
  Source: corpus `bybit/2026-10-05/ws/clean_publicTrade_BTCUSDT.jsonl`; date 2026-10-05; symbol
  BTCUSDT; env: public live stream shape (no account data); redaction: derived output of an
  already-redacted corpus, no identifiers. Regenerate from `services/api` with
  `CV_REGEN_GOLDEN=1 pytest tests/unit/bars/test_time_builder_golden.py` and review the diff.
- `golden/bars/activity_bars_BTCUSDT.jsonl` — E12-S02 tick/volume bars (tick:50, tick:500, vol:5,
  vol:0.25, one bar per line). Source: same corpus, date, symbol and env as above; redaction: derived
  output of an already-redacted corpus, no identifiers. Regenerate with
  `CV_REGEN_GOLDEN=1 pytest tests/unit/bars/test_activity_builders_golden.py` and review the diff.
- `golden/bars/threshold_bars_BTCUSDT.jsonl` — E12-S03 range/delta bars (range:20, delta:1,
  delta:2, one bar per line; the ticket's `delta:500` is replaced by delta:1/2 because it would
  yield a single bar on this 137 BTC day). Source: same corpus, date, symbol and env as
  above; redaction: derived output of an already-redacted corpus, no identifiers. Regenerate with
  `CV_REGEN_GOLDEN=1 pytest tests/unit/bars/test_threshold_builders_golden.py` and review the diff.

## Scripts

- `pnpm --filter @candleviewer/fixtures verify` — runs the redaction check
  over `raw/` and `golden/`.
- `pnpm --filter @candleviewer/fixtures test` — Vitest unit tests for the
  verify script itself.
