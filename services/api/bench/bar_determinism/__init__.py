"""E12-T04 bar-builder determinism harness (`24-internal-schemas.md` §3.4, BI-1..BI-6).

Test infrastructure only: nothing under `candleviewer/` imports this package.
- `generator`  seeded, offline synthetic `TradeEvent` tapes with adversarial patterns;
- `reference`  independent, naive builders written from the §3.3 spec text (the oracle);
- `invariants` BI-1..BI-6 checks + reference cross-check, returning named `Violation`s;
- `comparator` field-by-field, plain-text bar diff (index, field, expected, actual);
- `goldens`    recorded-day golden files and the only (explicit) regeneration path;
- `throughput` per-builder rebuild throughput vs the committed baseline (extends E12-K01).
"""
