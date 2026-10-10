"""E12-Q02 bar-builder golden conformance suite (`24-internal-schemas.md` §3.3/§3.4).

Test infrastructure only: nothing under `candleviewer/` imports this package. It extends the
E12-T04 harness in `bench.bar_determinism` (generator, comparator, tapes) and is separate
because it needs `asyncio` to drive the live `BarBuilderSet`.
- `runner`  feeds tapes through the `BarBuilderSet` fan-out and explains the first divergence;
- `bank`    plans/writes the tapes, goldens and `MANIFEST.toml` (explicit regeneration only).
"""
