# @candleviewer/chart-engine

Custom WebGL2 chart engine (candles, footprint, volume/market profile, CVD, DOM
heatmap). See `docs/plan/26-chart-engine-design.md` and ADR-0002.

**Hard rule (C-2.16):** no React, no DOM globals in `src/core`/`src/layers`, no
`fetch`, no Bybit/exchange knowledge. `pnpm lint` enforces this; violations
cite C-2.16 in the error message.

This is an E02-T03 scaffold: directory structure, build (`tsup`), test
(Vitest, ≥85% coverage gate) and bench harness contract are wired; no
rendering code, layers or worker logic exist yet (E06 spike, E11 core).

## Scripts

- `pnpm --filter @candleviewer/chart-engine build` — tsup ESM build with `.d.ts`.
- `pnpm --filter @candleviewer/chart-engine test` / `test:cov` — Vitest.
- `pnpm --filter @candleviewer/chart-engine bench` — writes `bench/results.json`
  (`frameTimeMs.{p50,p95,p99}`, `drawCalls`, `memoryMb`); `bench:baseline` writes
  `bench/baseline.json` for the `main`-branch comparison (CONSTITUTION §9 #16).
