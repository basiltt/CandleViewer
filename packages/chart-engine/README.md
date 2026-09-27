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

## Benchmark harness (E06-K01)

`bench/` is a deterministic, seeded benchmark harness for the M0 report (see
`docs/plan/06-performance-and-load-standard.md` §7, `docs/plan/26-chart-engine-design.md`
§13). It is **not** production engine code — it drives whatever scene a
`BenchScene` implementation (`bench/scene.mjs`) provides via a tiny interface,
so the K02/K03/K04 prototype scenes plug in unmodified.

```sh
pnpm bench --scenario=B5 --runtime=chromium --reps=3 --seed=20260928
```

- `--scenario` — one of `B1 B2 B3 B4 B5 B7 B9 B10` (`bench/driver.mjs`
  `SCENARIOS`); each maps to a time-parameterised scripted input sequence
  (pan, zoom sweep, footprint hold, heatmap stream, combined, live-update
  storm, cold-init, 30-min soak) so a slow machine executes the same logical
  motion as a fast one.
- `--runtime` — `chromium` (default/only wired target today), or `electron`/
  `tauri` (stubbed per this ticket's scope — real driving is E06-T01).
- `--reps` — repetitions; **default 3**. Fewer than 3 marks the report
  `"not admissible for ADR evidence"` (`bench/stats.mjs`).
- `--seed` — any string/number, hashed to a 32-bit seed for the mulberry32
  PRNG in `bench/fixtures/rng.mjs`; the fixture generator is byte-reproducible
  for a given seed (asserted by `test/bench/fixtures-determinism.test.ts`).

Every run writes `bench/report-<scenario>.json` (schema: `scenario, runtime,
runtimeVersion, machine{cpu,gpu,driver,os,webview2Version?}, seed, lodProfile,
repetitions, admissibleForAdrEvidence, p50, p95, p99, perStageMs{},
unattributedMs, drawCalls, uploadedBytesPerSec, textureMemMB,
peakProcessMemMB, peakProcessMemSource, gpuFlags[]}`) and
`bench/report-<scenario>.md` (human summary); both are generated artefacts
and are **not** committed (see `.gitignore`). `perStageMs` covers the nine
frame stages named in `06-performance-and-load-standard.md` §4.3 (input
handling, data-window recompute, candle geometry, footprint text/geometry,
heatmap upload, pane redraw, overlay redraw, DOM-mirror sync,
composite+present); the residual left over from the measured frame time is
reported as `unattributedMs` and the report writer fails the run if it
exceeds 10%.

The pinned headless-Chromium GPU flag set (`bench/report.mjs`
`PINNED_CHROMIUM_FLAGS`, printed in every report so results stay comparable
across weeks) is:

```
--use-gl=angle --use-angle=swiftshader --disable-gpu-vsync --enable-webgl2 --force-color-profile=srgb
```

The machine descriptor (CPU, GPU, driver, OS, and — on Tauri — the WebView2
runtime version) is captured automatically by `bench/machine.mjs`; a run
missing any required field fails rather than reporting anonymous numbers.
