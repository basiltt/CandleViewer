# Bar determinism goldens (E12-T04)

Source: `packages/fixtures/bybit/2026-10-05/ws/clean_publicTrade_BTCUSDT.jsonl` (sha256 pinned in
`manifest.json`), 542 public trades, BTCUSDT, env=live public stream, tick 0.1, ~3 h; provenance as
in `../../../bybit/README.md` / `README.trades.md` (built from documented shapes, exception #1778 A;
replace with an E16 recorder capture when it lands — a new capture is a new golden set).
Redaction: public `publicTrade.*` frames only; no auth/private frames, keys, signatures, UIDs or
order ids (asserted by `test_fixture_day_is_public_market_data_only`).

One `<label>.jsonl` per builder kind/parameter, one canonical bar row per line (Decimals as their
exact strings). Generated, never typed: `cd services/api && uv run python -m
bench.bar_determinism.regen_goldens --write --reason "<why>"` — refuses in CI, without a reason, or
when output changed without a `BUILD_VERSIONS` bump (`candleviewer/bars/rows.py`) in the same commit.
