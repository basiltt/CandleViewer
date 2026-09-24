# -*- coding: utf-8 -*-
"""E46 part 2: instrumentation + frontend optimisation tasks."""
from _e46_lib import T

tickets = []

tickets.append(T("E46-T01", "Task",
    "Emit machine-readable per-stage frame timings from the engine and the benchmark harness",
    ["type/tech", "area/chart-engine", "priority/p1", "perf"],
    "chart-engine", "Sprint 23", "P1 High", "Development", "R2 Render performance", 5, "E46",
    ["E46-K01", "E11", "E04"],
    """## Context
`docs/plan/06-performance-and-load-standard.md` §4.3 allocates the 16.6 ms frame budget across nine named stages, and §8 step 2 of the profiling playbook makes stage-attribution the **mandatory first step** of every regression investigation: "identify which stage regressed before profiling within it". Today that breakdown exists only as a table in a markdown file — the engine emits an aggregate frame time and nothing else, so an engineer who sees "p95 went from 14 ms to 17 ms" has no choice but to re-profile from scratch, which is exactly what the playbook forbids. §7.1 additionally requires the harness to output "p50/p95/p99 frame time overall **and per-stage** (from §4.3's breakdown)" — a requirement the current harness does not meet.

This task makes the stage breakdown real, in both directions: in the benchmark harness (for CI and the profiling playbook) and in the live app at a 2 Hz sampling rate (for SCR-046 and for the pushed `fe_frame_time_ms` field metric in `docs/plan/20-architecture.md` §12.1). It is the first engineering ticket of E46 because every subsequent optimisation ticket (T02, T03, T05, T07, T09) is required to prove its improvement with these numbers.

The render loop lives in a worker with OffscreenCanvas (`docs/plan/26-chart-engine-design.md` §6), so naive `Performance.mark()` on the main thread sees an opaque box. E46-K01 answers how to correlate worker marks with main-thread marks; this task implements whatever K01 recommends.

## Scope / Deliverables
- `packages/chart-engine/src/telemetry/stages.ts` — a zero-allocation stage timer with the nine stage ids fixed to `06-…` §4.3 exactly: `input`, `data_window`, `bar_geometry`, `footprint_text`, `heatmap_upload`, `pane_redraw`, `overlay_redraw`, `dom_mirror`, `composite`.
- Instrumentation call sites at each stage boundary in the worker render loop, using `Performance.mark()`/`measure()` per `06-…` §7.2, with a compile-time flag so the marks can be stripped from a non-instrumented build if their cost proves non-negligible.
- Worker→main correlation per the E46-K01 recommendation (expected shape: shared `performance.timeOrigin` reconciliation + a 2 Hz structured stats post on the existing stats channel, **not** per-frame `postMessage`).
- Ring-buffer accumulation of per-stage samples with p50/p95/p99 computed over a rolling window, so no per-frame allocation and no unbounded growth.
- `packages/chart-engine/bench` harness output extended to a versioned JSON report: overall p50/p95/p99, per-stage p50/p95/p99, per-stage budget from §4.3, pass/fail per stage, plus run metadata (commit, runner, GPU string, repeat count).
- Export to the field: populate `fe_frame_time_ms{stage}` (histogram), `fe_dropped_frames_total`, `fe_ws_decode_ms` and `fe_gpu_memory_mb` from `docs/plan/20-architecture.md` §12.1 via the existing pushed-frontend-metrics path from E04.
- A `bench/baselines/` JSON schema for the stored baselines that E46-T10's gate compares against (§7.4).
- Stage-attribution report renderer: a human-readable table printed by the harness naming any stage over its §4.3 slice.

## Out of scope
- The CI gate itself (E46-T10) — this ticket produces the numbers, T10 enforces them.
- The SCR-046 UI (E46-S01) — this ticket exposes the data on the stats channel; S01 renders it.
- Backend span instrumentation (E46-T04).
- Any optimisation. This ticket must be performance-neutral; if instrumentation costs more than 0.2 ms/frame in the instrumented build, the compile-time strip flag is the mitigation and the measured cost is recorded.

## Acceptance criteria
```gherkin
Scenario: The harness reports every stage
  Given the chart-engine benchmark harness runs scenario B5 from docs/plan/26-chart-engine-design.md §13
  When the run completes
  Then the JSON report contains p50, p95 and p99 for each of the nine stages named in docs/plan/06-performance-and-load-standard.md §4.3
  And each stage is marked pass or fail against its documented slice
  And the sum of the stage p50 values is within 10% of the overall p50 frame time

Scenario: A stage regression is attributed automatically
  Given a deliberate 3ms sleep is injected into the footprint text path
  When the harness runs
  Then the report names footprint_text as the stage exceeding its 4ms slice
  And no other stage is reported as failing

Scenario: Instrumentation is cheap in the live app
  Given the live app runs a 4-pane workspace with stage sampling enabled at 2Hz
  Then the measured overhead of the instrumentation is at or below 0.5ms per frame
  And no per-frame heap allocation is attributable to the stage timer over a 60-second capture

Scenario: The worker boundary does not lose stages
  Given the render loop runs in a worker with OffscreenCanvas
  When stage samples are read on the main thread
  Then all nine stages are present and their timestamps are monotonic on a single reconciled clock

Scenario: Field metrics are populated
  Given the app has been running for five minutes with metrics push enabled
  Then fe_frame_time_ms carries a stage label, and fe_dropped_frames_total, fe_ws_decode_ms and fe_gpu_memory_mb are non-empty
```

## Technical notes / design
Stage ids are a closed enum, not free strings — this bounds Prometheus label cardinality (a stated NFR of US-OBS-001: "cardinality bounded and documented"). Nine stages × the existing `env` label is the entire cardinality contribution.

Sampling shape:
```ts
const t = stages.begin("footprint_text");   // records a high-res timestamp into a preallocated slot
// ... stage work ...
stages.end(t);                              // no allocation, no string work in the hot path
```
`stages.snapshot()` is called on the 2 Hz stats tick, computes percentiles from the ring buffer (P² or a fixed-bucket histogram — a sorted-copy percentile is acceptable in the harness but **not** in the live app), and posts a plain object.

Clock reconciliation: worker and main thread both report `performance.timeOrigin`; the delta is computed once at worker start with a three-round ping-pong taking the minimum RTT sample, and stored. Re-measured if the page is backgrounded for >60 s.

Harness report shape (versioned, `"schema": 1`) is the contract E46-T10 and E46-Q01 both consume; changing it later requires bumping `schema` and updating both.

Error handling: if a stage's `end()` is never called (an early-return bug), the sample is discarded and a `stage_unbalanced_total` counter increments rather than recording a garbage duration — a silent wrong number is worse than a missing one.

## Test plan
- **Unit** (`packages/chart-engine`, ≥85 % on new lines): ring-buffer wrap; percentile correctness against a known distribution; unbalanced begin/end discarded and counted; snapshot allocation-free (asserted via a heap-delta harness); stage enum exhaustiveness.
- **Contract**: harness JSON report validated against its JSON Schema in CI; a golden-report fixture test so an accidental shape change fails loudly.
- **Integration**: run B1, B3, B4, B5 from `26-chart-engine-design.md` §13 and assert every stage is present and non-zero where it should be, zero where it legitimately is (e.g. `heatmap_upload` on a candle-only scene).
- **Perf**: instrumented vs stripped build compared on B5; delta recorded in the PR and must be ≤0.2 ms p95.
- **Injected-regression test**: the 3 ms sleep scenario above, kept as a permanent test so the attribution machinery cannot silently break.

## Security notes
The harness report and the pushed metrics carry GPU vendor/renderer strings, which are a fingerprinting surface. Per `docs/plan/04-security-program.md` the metrics endpoint is private-network-bound (US-OBS-001 NFR) so this is acceptable inside the deployment, but the GPU string must **not** be included in any artefact that leaves the machine without the user's explicit action (the SCR-046 "copy diagnostics" action is such an explicit action and must say what it includes). No market, order or account data enters a stage sample — assert this in review. Data classification: operational telemetry, non-secret.

## Accessibility notes
N/A — no UI surface in this ticket. Constraint inherited: the `dom_mirror` stage must continue to be measured, because `docs/plan/06-…` §4.4 forbids desyncing the DOM-mirror to save frame time, and this instrumentation is how that is policed.

## Performance notes
Budgets: instrumentation overhead ≤0.2 ms p95 per frame in the instrumented build, ≤0.5 ms per frame for the in-app 2 Hz sampling path (SCR-046's stated budget), ≤1 % CPU total measurement overhead (US-OBS-002 NFR). Zero per-frame allocation is a hard requirement — GC pauses are themselves a frame-budget risk.

## Observability
Adds `fe_frame_time_ms{stage}` histogram, `stage_unbalanced_total` counter; populates `fe_dropped_frames_total`, `fe_ws_decode_ms`, `fe_gpu_memory_mb` (`20-architecture.md` §12.1). Optionally writes the 2 Hz snapshot to QuestDB `engine_metrics` (`docs/plan/21-database-schema.md` §4.13) so frame data can be joined to market data — §4.13's stated purpose ("did we drop frames during the 14:30 liquidation cascade?").

## Definition of Done
- [ ] All five Gherkin scenarios covered by automated tests.
- [ ] Coverage ≥85 % on new/changed lines in `packages/chart-engine`.
- [ ] Harness JSON Schema committed; golden-report fixture test green.
- [ ] Instrumentation overhead measured and recorded in the PR body with before/after numbers.
- [ ] `docs/plan/26-chart-engine-design.md` §13 updated to state that benchmarks now emit per-stage output.
- [ ] `docs/plan/20-architecture.md` §12.1 row for frontend metrics updated with the stage label.
- [ ] perf: B1/B3/B4/B5 re-run, no regression beyond 5 %.
- [ ] Reviewed by a chart-engine code owner + the Architect.

## Dependencies
- **E46-K01** decides the worker-correlation and tooling approach this task implements.
- **E11** supplies the render loop and worker/stats channel being instrumented.
- **E04** supplies the pushed-frontend-metrics transport.

## Branch
`feat/e46-perf-stage-instrumentation`. PR size: ~350 LOC; split the metrics-push wiring into a second PR if it grows.

## References
`docs/plan/06-performance-and-load-standard.md` §4.3, §7.1, §7.2, §8 · `docs/plan/26-chart-engine-design.md` §6, §13 · `docs/plan/20-architecture.md` §12.1 · `docs/plan/21-database-schema.md` §4.13 · `docs/plan/11-user-stories.md` US-OBS-002 · `docs/plan/14-screens-catalogue.md` SCR-046
"""))

tickets.append(T("E46-T02", "Task",
    "Optimise the footprint cell text path against its 4ms frame slice",
    ["type/tech", "area/chart-engine", "priority/p1", "perf"],
    "chart-engine", "Sprint 23", "P1 High", "Development", "R2 Render performance", 5, "E46",
    ["E46-T01", "E18"],
    """## Context
`docs/plan/06-performance-and-load-standard.md` §4.3 allocates footprint cell text/geometry **≤4 ms** — the largest single slice — and explicitly flags it as "the largest CPU-side cost per research (text-heavy rendering is the flagged engineering risk)". `docs/plan/26-chart-engine-design.md` §3.7 designed the SDF text path and measured ~0.9 ms CPU batching at 12,500 glyphs, and §13 gate **B3** requires 2,500 visible footprint cells with text at ≤16 ms p95 with "text batching ≤2.0 ms, ≤2 text draw calls". Between that measurement and R5 the product grew order lines, position overlays, drawings, detector markers and multi-pane layouts, all competing for the same frame — and the B3 secondary gate has never had a dedicated optimisation pass, only a "it passes today" observation.

This ticket is the one profile-guided optimisation pass on the flagged riskiest stage, executed strictly per the `06-…` §8 playbook, using the stage attribution delivered by E46-T01.

## Scope / Deliverables
- Profile the `footprint_text` stage on B3 and B5 (`26-chart-engine-design.md` §13) plus a deliberately adversarial scene (maximum cell density at the LOD text threshold, 4 panes, imbalance highlighting on) using Chrome DevTools Performance + `Performance.mark` correlation and a WebGL frame debugger per `06-…` §8 step 3.
- Optimise the SDF glyph path in `packages/chart-engine/src/text` and the footprint layer's text batching in `packages/chart-engine/src/layers/footprint`. Candidate work, to be confirmed by the profile and not assumed: glyph-run caching keyed by (value, price-precision) so unchanged cells never re-lay-out; dirty-rect/changed-cell-only re-batching instead of whole-viewport rebuild; number formatting off the hot path (precomputed digit atlas / integer fast path instead of `toFixed`); instance-buffer reuse with `bufferSubData` over reallocation; avoiding per-frame `Map`/string allocation in the layout loop.
- Verify and, where the profile shows it engages too late or too early, tune the **LOD text-hiding threshold** — `06-…` §4.3 states LOD text-hiding exists "to protect this budget, not to save GPU time alone", and §4.4 step 2 makes footprint text density the second thing shed under degradation.
- Record before/after per-stage numbers for B3, B5 and the adversarial scene in the PR body (mandatory per §8 step 5).
- If the profile shows the ≤4 ms slice cannot be met at the documented density without visual compromise, that is a finding, not a failure: record it, propose the allocation change, and update `06-…` §4.3 through a reviewed docs change with the Architect — do not silently miss the budget.

## Out of scope
- Changing what footprint cells *mean* or how they are aggregated (E18 owns the semantics; this is a rendering optimisation only).
- Heatmap upload (E46-T03), backend footprint aggregation (E46-T07).
- Any change to the imbalance or stacked-imbalance visual rules.
- New glyph rendering techniques requiring a new dependency, unless the profile proves the existing SDF path cannot meet the budget and an ADR is raised.

## Acceptance criteria
```gherkin
Scenario: The footprint text stage fits its slice
  Given the benchmark scene B3 (2,500 visible footprint cells with text)
  When the harness runs three times and the median is taken
  Then the footprint_text stage p95 is at or below 4ms
  And text batching p95 is at or below 2.0ms and text draw calls are at most 2

Scenario: The combined scene still holds 60fps
  Given the benchmark scene B5 (candles + footprint + heatmap + 3 indicators + 50 order lines)
  Then overall p95 frame time is at or below 16.7ms
  And the footprint_text stage has improved relative to the pre-optimisation baseline recorded in this ticket

Scenario: Unchanged cells cost nothing
  Given a footprint pane where only the forming bar's cells change between frames
  When a frame renders
  Then the number of glyph layouts performed is proportional to the changed cells only, not to the visible cell count

Scenario: LOD still protects the floor
  Given the worst-case scene drives the engine into the degradation ladder
  When footprint text LOD engages per docs/plan/06-performance-and-load-standard.md §4.4 step 2
  Then cell colour blocks remain correct and legible, no numeric value is shown truncated or wrong, and frame rate stays at or above 30fps

Scenario: No visual regression
  Given the footprint visual-regression fixture set
  Then rendered output is pixel-identical to the pre-optimisation baseline at every tested zoom level, except where a change is explicitly listed and design-approved in this ticket
```

## Technical notes / design
Method is fixed by `06-…` §8 and must be followed in order: reproduce deterministically on the versioned synthetic dataset → stage-attribute with E46-T01's output → deep-dive with DevTools/Spector → fix → re-run the exact harness → record before/after. "Should be faster now" without harness numbers is an automatic review rejection per the epic.

Likely highest-yield item based on `26-chart-engine-design.md` §3.7: the layout step, not the draw step. An SDF atlas draw of 12,500 glyphs is ~2 text draw calls; the cost is building the per-glyph instance data. Caching glyph runs per distinct rendered *string* (footprint values repeat heavily within a pane — many cells share the same volume digits at coarse precision) should collapse the layout work by a large factor. Cache must be bounded (LRU, sized from the MemoryGovernor budget in `26-chart-engine-design.md` §7) and invalidated on font/DPR/price-precision change.

Do not trade correctness for speed: a cell's displayed number must always match the aggregated value for that cell. Any rounding/precision shortcut is a product change and needs E18's owner.

## Test plan
- **Unit**: glyph-run cache hit/miss/eviction; cache invalidation on DPR change, font change, precision change; integer fast-path formatting equals `toFixed` output across a fuzzed value range including negatives, zeros and the maximum expected volume.
- **Visual regression**: existing footprint screenshot fixtures at 3 zoom levels × light/dark × 1× and 2× DPR, pixel-compared.
- **Perf**: B3 and B5 gates, three runs, median compared to the baseline committed at the start of this ticket; the adversarial scene recorded as a new tracked (non-gating) scenario.
- **Integration**: LOD threshold crossing in both directions with no flicker (mirrors B2's "no LOD flicker" secondary gate).
- Coverage ≥85 % on changed lines.

## Security notes
No new data surface, no new dependency expected. If an optimisation introduces a cache keyed by rendered content, confirm the cache lives only in renderer memory and is never serialised into a diagnostics artefact — footprint values are market data, not secret, but the principle of not widening artefact contents holds. SAST/SCA must stay clean; any new dependency requires Security review and an ADR.

## Accessibility notes
The DOM-mirror accessibility layer (`docs/plan/05-accessibility-standard.md` §6.1) must remain in sync with rendered output — `06-…` §4.4 names desyncing it as "never acceptable". If text LOD hides a numeric value visually, the DOM-mirror must still expose the underlying value to a screen reader, because hiding it visually is a density decision, not a data decision. Assert this in an axe/DOM-mirror integration test.

## Performance notes
Binding: §4.3 `footprint_text` ≤4 ms; B3 ≤16 ms p95 with text batching ≤2.0 ms and ≤2 text draw calls; B5 ≤16.7 ms p95 with ≤40 total draw calls; degraded floor 30 fps.

## Observability
No new metrics; this ticket is a consumer of E46-T01's `fe_frame_time_ms{stage="footprint_text"}`. Optionally add a glyph-cache hit-rate gauge to the SCR-046 diagnostics payload if the profile shows it is the key health signal.

## Definition of Done
- [ ] All five Gherkin scenarios verified by automated tests.
- [ ] Before/after per-stage harness numbers for B3, B5 and the adversarial scene in the PR body.
- [ ] B3 secondary gates (≤2.0 ms batching, ≤2 draw calls) green.
- [ ] Visual-regression fixtures green or every diff explicitly design-approved.
- [ ] Coverage ≥85 % on changed lines; no dependency added without an ADR.
- [ ] DOM-mirror sync test green under text LOD.
- [ ] If the 4 ms slice proved unattainable, `docs/plan/06-…` §4.3 updated with the Architect's approval and the reason.
- [ ] Reviewed by chart-engine code owner; demo = before/after evidence at Sprint Review.

## Dependencies
- **E46-T01** provides the stage attribution without which this work cannot be targeted or proven.
- **E18** owns the footprint layer and its visual/aggregation semantics.

## Branch
`feat/e46-perf-footprint-text`. PR size ≤400 LOC; if the profile yields several independent wins, ship them as separate PRs each with its own before/after numbers.

## References
`docs/plan/06-performance-and-load-standard.md` §4.3, §4.4, §8 · `docs/plan/26-chart-engine-design.md` §3.7, §7, §11, §13 (B2, B3, B5) · `docs/plan/05-accessibility-standard.md` §6.1 · `docs/plan/11-user-stories.md` US-CHART-001
"""))

tickets.append(T("E46-T03", "Task",
    "Profile and tune the DOM heatmap texture upload path under real ring-wrap conditions",
    ["type/tech", "area/chart-engine", "priority/p1", "perf"],
    "chart-engine", "Sprint 23", "P1 High", "Development", "R2 Render performance", 3, "E46",
    ["E46-T01", "E21"],
    """## Context
`docs/plan/06-performance-and-load-standard.md` §4.3 allocates heatmap texture upload **≤2 ms** and §4.2 explains why it should be cheap: only the newest time-column is uploaded via `texSubImage2D`, so cost is bounded by depth (200 rows), not by trail length. Budget #14 requires the 100 ms visual cadence sustained at 200 depth with "≤1 dropped/coalesced frame per 10 s", and `docs/plan/26-chart-engine-design.md` §13 gate **B4** requires ≤10 ms p95 with "upload ≤12 KB/s, texture memory ≤20 MB".

The design is sound on paper. What has never been measured is the path under the *combination* that occurs in real use: the ring buffer wrapping (the newest column overwriting the oldest slot), a `priceOrigin` shift when price moves outside the current texture's price window (which forces a re-rasterisation, not a one-column update), and coarse-ring rollover for the longer trail — all potentially landing in the same frame during a volatile move, which is precisely when the user is watching. §4.2's "constant cost" claim is untested at that intersection.

## Scope / Deliverables
- Build a heatmap stress fixture that deterministically forces, within a scripted run: steady 100 ms columns, ring wrap, a `priceOrigin` shift, a coarse-ring rollover, and all three within one frame.
- Profile `packages/chart-engine/src/layers/heatmap` upload and draw with the E46-T01 stage timings plus a GPU frame debugger, measuring `texSubImage2D` cost, any implicit format conversion, any pipeline stall from uploading to a texture bound for drawing, and the cost of the re-rasterisation path.
- Optimise per the profile. Candidates to confirm, not assume: exact internal-format/type match to avoid driver-side conversion; `PIXEL_UNPACK_BUFFER` (PBO) double-buffering to decouple upload from draw; amortising or incrementalising the `priceOrigin` re-rasterisation across frames instead of doing it wholesale; ensuring the coarse ring's rollover is O(columns changed), not O(trail).
- Verify heatmap trail memory against the ceiling and the MemoryGovernor budgets in `26-chart-engine-design.md` §7 (B4: texture memory ≤20 MB).
- Verify budget #14's dropped/coalesced-frame criterion with a counted assertion, not an eyeball.
- Record before/after numbers for B4 and the stress fixture.

## Out of scope
- Backend heatmap aggregation and the `heatmap.*` WS topic payload shape (`docs/plan/23-ws-protocol.md` §3.4 binary kind 6) — E46-T05 covers fan-out serialisation.
- Heatmap visual design, colour mapping (green=bid/red=ask is a locked decision) or trail-length product defaults.
- `heatmap_cells` storage/query tuning (E46-T08).

## Acceptance criteria
```gherkin
Scenario: Steady-state upload fits its slice
  Given the B4 benchmark scene (100ms columns, 4h trail, panning)
  Then the heatmap_upload stage p95 is at or below 2ms
  And overall p95 frame time is at or below 10ms
  And measured upload bandwidth is at or below 12 KB/s and heatmap texture memory is at or below 20 MB

Scenario: The pathological frame does not break the budget
  Given a frame in which the ring wraps, priceOrigin shifts and the coarse ring rolls over simultaneously
  Then the frame time for that frame stays at or below 33.3ms (the 30fps floor)
  And the following frame is back within 16.6ms
  And no heatmap column is lost or duplicated

Scenario: Cadence is sustained and counted
  Given the realistic-peak scenario running for 10 minutes at 200 depth
  Then the 100ms visual refresh cadence is sustained with at most 1 dropped or coalesced frame per 10 seconds
  And the dropped/coalesced count is reported by the harness as a number, not inferred visually

Scenario: Degradation relaxes cadence, not correctness
  Given the engine enters degraded mode and relaxes heatmap cadence toward 250ms per §4.4 step 1
  Then the displayed heatmap remains a correct representation of book state at the coarser cadence
  And the reduced-detail indicator is shown
```

## Technical notes / design
Follow `06-…` §8 in order; stage-attribute first with E46-T01's `heatmap_upload` timing before touching code.

The `priceOrigin` shift is the suspected worst case: it is not a one-column update but a re-map of the whole texture's price axis. Two viable shapes if it proves expensive — (a) over-provision the price window with margin so shifts are rare and batched, (b) incrementalise the re-rasterisation over N frames with the un-remapped region rendered from the previous texture. Choose from the profile; record the reasoning in the PR.

PBO double-buffering is a real win only if the profile shows a synchronous stall on `texSubImage2D`; if it does not, do not add the complexity. Explicitly note which candidate optimisations were rejected by the profile and why — a rejected-by-measurement list is a deliverable, because it stops the next engineer re-litigating them.

## Test plan
- **Unit**: ring-index arithmetic across wrap; column ordering after wrap; `priceOrigin` shift remap correctness (a known book state maps to known texel positions before and after); coarse-ring rollover preserves aggregate correctness.
- **Visual regression**: heatmap screenshots before/after wrap, before/after a `priceOrigin` shift, and at both cadences.
- **Perf**: B4 three-run median vs the baseline recorded at ticket start; the pathological-frame fixture as a new tracked scenario with its own recorded number.
- **Integration**: dropped/coalesced-frame counter asserted against budget #14 over a 10-minute scripted run.
- Coverage ≥85 % on changed lines.

## Security notes
No new data surface. Heatmap data is market data (non-secret). If PBOs or additional GPU buffers are introduced, confirm they are released on context loss and on pane teardown — a leaked GL resource on repeated context-loss/restore (SCR-047's auto-retry path) is both a memory and a stability issue, and feeds E46-T06's leak hunt.

## Accessibility notes
The heatmap's accessible alternative (DOM-mirror / data readout per `docs/plan/05-accessibility-standard.md` §6.1) must remain in sync at whatever cadence is active; a relaxed visual cadence must relax the announced data identically rather than the two drifting apart.

## Performance notes
Binding: §4.3 `heatmap_upload` ≤2 ms; budget #14 100 ms cadence at 200 depth with ≤1 dropped/coalesced frame per 10 s; B4 ≤10 ms p95, upload ≤12 KB/s, texture memory ≤20 MB; 30 fps floor on the pathological frame.

## Observability
Adds a heatmap dropped/coalesced-column counter to the SCR-046 diagnostics payload and to the harness report (it is a budget-#14 pass criterion and must be a number the CI gate in E46-T10 can read).

## Definition of Done
- [ ] All four Gherkin scenarios verified by automated tests.
- [ ] Before/after B4 numbers and pathological-frame numbers in the PR body.
- [ ] Rejected-optimisation list with measured reasons recorded in the ticket.
- [ ] Visual-regression fixtures green.
- [ ] Texture-memory ceiling asserted; GL resources verified released on context loss and teardown.
- [ ] Coverage ≥85 % on changed lines.
- [ ] Reviewed by chart-engine code owner.

## Dependencies
- **E46-T01** for `heatmap_upload` stage attribution and the harness report.
- **E21** owns the DOM heatmap layer being tuned.

## Branch
`feat/e46-perf-heatmap-upload`. PR size ≤400 LOC.

## References
`docs/plan/06-performance-and-load-standard.md` §4.2, §4.3, §4.4, §8, §2 budget #14 · `docs/plan/26-chart-engine-design.md` §3.8, §7, §13 (B4) · `docs/plan/23-ws-protocol.md` §3.4 · `docs/plan/05-accessibility-standard.md` §6.1
"""))

tickets.append(T("E46-T06", "Task",
    "Hunt and fix frontend memory leaks against the 1.5GB workspace ceiling",
    ["type/tech", "area/chart-engine", "priority/p1", "perf"],
    "chart-engine", "Sprint 24", "P1 High", "Development", "R2 Render performance", 5, "E46",
    ["E46-T02", "E46-T03"],
    """## Context
Budget #7 in `docs/plan/06-performance-and-load-standard.md` §2 caps the frontend at **≤1.5 GB resident** for a fully-loaded workspace (100k bars, all overlays, 4-pane layout), measured over a 2 h soak, and §7.3's chart-engine memory soak asserts "no monotonic growth beyond a documented variance band". `docs/plan/26-chart-engine-design.md` §13 gate **B10** adds a 30-minute live-feed soak with peak ≤600 MB and "no monotonic growth beyond 5 %/30 min". §6.2 states the mechanism the ceiling depends on: windowed/virtualized structures where only visible+prefetch bars are materialised at full fidelity.

R5's exit criterion is stricter than anything measured so far: a **72-hour** continuous-use soak with flat memory (owned by E46-Q02). A leak that is invisible at 30 minutes and merely suspicious at 2 hours is fatal at 72 hours. This ticket is the deliberate hunt for those leaks, run before Q02 so Q02 is a proof rather than a discovery.

Typical suspects in this codebase, all to be confirmed by measurement: GL resources not released on pane close or on context-loss/restore (SCR-047 auto-retries ×3); WS subscription handlers retained after unsubscribe; RxJS subscriptions not torn down on pane teardown; the LRU caches introduced by E46-T02 and E46-T03 growing unbounded; detached DOM from the DOM-mirror layer; drawing-tool objects retained after deletion; replay session buffers not freed; worker-side buffers retained after a symbol switch.

## Scope / Deliverables
- A repeatable leak-hunt harness: a Playwright-driven session performing a scripted "churn" cycle — open pane → load 100k bars → enable all overlays → switch symbol → switch timeframe → open and close a replay session → force a WebGL context loss and restore → close pane — repeated N times, sampling `performance.measureUserAgentSpecificMemory()` / Electron `process.getProcessMemoryInfo()` and heap snapshots at cycle boundaries.
- Heap-snapshot diffing between cycle N and cycle N+10 with an assertion that the retained-object delta for engine-owned classes is bounded.
- A GL-resource ledger in debug builds: every texture, buffer, VAO, program and framebuffer allocation and deletion is counted by owner, and a leak is a non-zero balance after teardown. This is the single highest-value piece of the ticket and should outlive it as a permanent guard.
- Fix every leak found; each fix carries a regression test at the appropriate layer.
- Verify the MemoryGovernor (`26-chart-engine-design.md` §7) actually evicts under pressure and that its budgets match budget #7 and the caches added in E46-T02/T03.
- Extend the §7.3 memory-soak harness from 2 h to a parameterised duration so E46-Q02 can drive 72 h from the same code.
- Document the "documented variance band" that §7.3 references but does not currently define — a concrete number (e.g. peak-to-trough RSS band and a maximum permitted linear-regression slope over the window), agreed with the Architect and written into `docs/plan/06-…` §7.3.

## Out of scope
- Backend memory (E46-T07).
- Running the 72 h soak itself (E46-Q02).
- Reducing steady-state memory below budget as an optimisation goal — this ticket is about *growth*, not *level*, except where the level breaches budget #7.

## Acceptance criteria
```gherkin
Scenario: Churn does not leak
  Given the leak-hunt harness runs 50 churn cycles
  Then resident memory after cycle 50, measured after a forced GC, is within the documented variance band of the value after cycle 10
  And the heap-snapshot retained-size delta for engine-owned classes is bounded and reported

Scenario: GL resources balance to zero
  Given a debug build with the GL-resource ledger enabled
  When a pane is opened and then closed
  Then every texture, buffer, VAO, program and framebuffer allocated by that pane has been deleted, and the ledger balance for that pane is zero

Scenario: Context loss and restore does not accumulate
  Given the WebGL context is lost and restored three times, matching SCR-047's auto-retry behaviour
  Then GPU memory after restoration is within the variance band of the pre-loss value
  And no duplicate resources are registered in the ledger

Scenario: The soak gate still holds
  Given benchmark B10 (30-minute live-feed memory soak)
  Then peak memory is at or below 600MB and growth does not exceed 5% over the window

Scenario: The workspace ceiling holds
  Given a fully-loaded 4-pane workspace with 100k bars and all overlays over a 2-hour soak
  Then resident memory stays at or below 1.5GB throughout
  And the MemoryGovernor evicts rather than allowing the ceiling to be breached
```

## Technical notes / design
Measure, then fix: a heap snapshot diff naming a retained class is the entry ticket to any fix in this PR. `06-…` §8 applies here too — the "stage" equivalent is the retaining path.

The GL-resource ledger should wrap the GL context in debug builds only (zero cost in release), keyed by an owner tag pushed/popped around pane construction. This makes "which pane leaked" a lookup rather than an investigation, and it is the guard that stops leaks returning after E46 closes.

Forced GC: use the Playwright/CDP `HeapProfiler.collectGarbage` before each measurement so that an un-collected-but-collectable heap is never mistaken for a leak — a false positive here costs days.

Variance band definition must be defensible: RSS is noisy because of allocator behaviour and GPU driver caching. Propose band = (max − min over the last third of the window) ≤ 10 % of the mean, **and** the least-squares slope over the full window ≤ 1 % of mean per hour. Confirm the numbers empirically against a known-good build before writing them into the standard.

## Test plan
- **Unit**: teardown methods release every resource they own (table-driven over the layer registry); MemoryGovernor eviction ordering and budget arithmetic; LRU caches from T02/T03 are bounded.
- **Integration**: churn harness at 50 cycles in nightly CI (not per-PR, for runtime); GL-ledger balance assertion per pane type.
- **Perf/soak**: B10 per-PR; 2 h workspace soak nightly; the parameterised harness handed to E46-Q02 for 72 h.
- **Regression**: every leak found gets a named test that fails on the pre-fix commit.
- Coverage ≥85 % on changed lines.

## Security notes
Heap snapshots contain live application data — order state, account identifiers, market data. They must be written to a gitignored local path, never attached to an issue or PR, and the harness must state this in its README. This is the same control E46-K01 and E46-X01 apply to profiling artefacts generally.

## Accessibility notes
The DOM-mirror layer is a leak suspect (detached DOM nodes on pane churn) and is in scope for the hunt. Fixes must not reduce the mirror's fidelity or its sync with rendered output — `06-…` §4.4 forbids desync.

## Performance notes
Binding: budget #7 ≤1.5 GB per workspace; B10 peak ≤600 MB, ≤5 % growth per 30 min; the newly-defined variance band; 72 h flat memory as the downstream R5 exit criterion.

## Observability
`fe_gpu_memory_mb` (`docs/plan/20-architecture.md` §12.1) populated from the GL-resource ledger's accounting rather than a guess; GL-ledger balance exposed in the SCR-046 diagnostics payload for debug builds.

## Definition of Done
- [ ] All five Gherkin scenarios verified.
- [ ] Every leak found is listed in the ticket with its retaining path, its fix, and its regression test.
- [ ] GL-resource ledger merged and enabled in debug builds.
- [ ] Variance band defined numerically and written into `docs/plan/06-performance-and-load-standard.md` §7.3 via a reviewed docs PR.
- [ ] Soak harness parameterised by duration and handed to E46-Q02.
- [ ] Coverage ≥85 % on changed lines; B10 green.
- [ ] Reviewed by chart-engine code owner + Architect (for the variance-band definition).

## Dependencies
- **E46-T02** and **E46-T03** land first because both introduce caches and GPU resources that are themselves leak candidates; hunting before they merge would mean hunting twice.

## Branch
`feat/e46-perf-frontend-leaks`. PR size: the ledger is one PR; each leak fix is its own small PR with its regression test.

## References
`docs/plan/06-performance-and-load-standard.md` §2 budget #7, §6.2, §7.3, §8 · `docs/plan/26-chart-engine-design.md` §7, §13 (B10) · `docs/plan/20-architecture.md` §12.1 · `docs/plan/14-screens-catalogue.md` SCR-047
"""))

tickets.append(T("E46-T09", "Task",
    "Build the startup and workspace-restore harness and hit the 3s cold-start budget",
    ["type/tech", "area/chart-engine", "area/web", "priority/p2", "perf"],
    "web", "Sprint 24", "P2 Medium", "Development", "R2 Render performance", 3, "E46",
    ["E46-T01"],
    """## Context
Budget #10 in `docs/plan/06-performance-and-load-standard.md` §2 is a **hard** budget: ≤3 s cold start from Electron app launch to "last-used workspace fully interactive, symbols subscribed", measured by an instrumented `app.whenReady()` → "workspace ready" event on reference hardware (§3.1). §9's load-test table lists "Startup time, cold launch — instrumented Electron launch harness, CI + manual on reference hardware". Budget #9 (bundle size, ≤8 MB gzipped, soft) is measured alongside it and gates at >+10 % vs the last tagged baseline. `docs/plan/26-chart-engine-design.md` §13 gate **B9** covers the engine's own slice: cold init to first frame with 100k bars ≤900 ms, SDF atlas from cache ≤5 ms.

Neither the harness nor the "workspace ready" event exists. Budget #10 is described as an R1 exit gate in §2 but has never been mechanically measured, which means it is currently an assertion rather than a fact — exactly the kind of gap R5 exists to close.

## Scope / Deliverables
- Define and emit the **`workspace_ready`** event with a precise, defensible definition: last-used workspace layout restored, every pane's initial data painted (not merely requested), every symbol subscription confirmed by the WS `sub` ack (`docs/plan/23-ws-protocol.md` §5), and the UI accepting input. Ambiguity here is the main risk — write the definition into `docs/plan/06-…` §2's budget-#10 row so it cannot drift.
- Instrument the intervening phases so a regression is attributable in the same spirit as §4.3: process launch → `app.whenReady()` → renderer created → bundle parsed/evaluated → auth/session restored → workspace layout loaded → WS connected and authenticated → subscriptions acked → first paint per pane → `workspace_ready`.
- An automatable cold-start harness (CI-runnable on the Electron build, plus a documented manual procedure on reference hardware per §3.1) producing a per-phase report over ≥3 runs with the median compared to a stored baseline, in the same report schema as E46-T01.
- A **workspace-restore** variant: restoring a heavy 4-pane workspace, measured separately from first-run startup because the two have different bottlenecks.
- Bundle-size measurement (budget #9) wired into the same report: gzipped initial bundle from the bundle analyzer, with the code-split boundary respected (chart-engine core counted, lazy-loaded heavy panels excluded).
- Optimise whatever the per-phase report says is over. Candidates to confirm, not assume: deferring non-critical module evaluation, SDF atlas cache warm (B9's ≤5 ms path), parallelising WS connect/auth with layout restore, prefetching the last-used workspace's first data window, and lazy-loading panels that are not in the restored layout.
- Cold-start and bundle-size results handed to E46-T10 for CI enforcement.

## Out of scope
- Backend startup time (covered under E46-T07's process-level work if it proves to matter).
- Changing what a workspace *is* or how layouts are persisted (owned by the LAY domain epics).
- Installer/update-download time — not part of budget #10's definition.

## Acceptance criteria
```gherkin
Scenario: Cold start meets budget
  Given a cold Electron launch on reference hardware with a previously-saved 4-pane workspace
  When the app starts three times and the median is taken
  Then the interval from process launch to workspace_ready is at or below 3 seconds

Scenario: A startup regression is phase-attributable
  Given a deliberate 500ms delay is injected into workspace layout loading
  When the harness runs
  Then the report names the layout-loading phase as the one that grew, without requiring a manual profile

Scenario: workspace_ready means genuinely ready
  Given workspace_ready has fired
  Then every pane in the restored layout has painted real data, every subscription has an acked sub_id, and a keyboard input is accepted and acted upon

Scenario: Bundle budget is measured and tracked
  Given the CI bundle-analyzer step runs on a merge to main
  Then the gzipped initial bundle size is reported
  And a size increase of more than 10% versus the last tagged baseline fails the soft gate and opens a tracked ticket

Scenario: Engine cold init holds its own gate
  Given benchmark B9 (cold init to first frame with 100k bars)
  Then time to first frame is at or below 900ms and the SDF atlas loads from cache in at most 5ms
```

## Technical notes / design
Measurement honesty is the whole point: `workspace_ready` must not fire on "layout painted with skeletons". The acked-subscription condition is what makes it meaningful — a workspace showing empty panes is not interactive in any sense the user recognises. Use the `sub` ack's `sub_id` from `docs/plan/23-ws-protocol.md` §5 as the machine-checkable condition.

Phase timings use the same report schema (`"schema": 1`) as E46-T01 so E46-T10 has one comparator implementation, not two.

Reference-hardware caveat (§3.1): CI runners are not reference hardware, so the CI gate must run against a *CI baseline* recorded on the CI runner, while the ≤3 s absolute figure is asserted by the documented manual procedure on reference hardware, re-run per release. Both numbers are recorded; conflating them would produce either a permanently-red or a permanently-meaningless gate.

Cold means cold: the harness must clear the OS file cache where the platform allows, or explicitly document that it measures warm-cache start and record the reference-hardware cold number manually. State which was done — an undocumented warm measurement presented as cold is worse than no measurement.

## Test plan
- **Unit**: phase-timer bookkeeping; `workspace_ready` predicate (all conditions required, any one missing keeps it unfired) table-driven over pane/subscription combinations.
- **Integration**: harness runs against the packaged Electron build in nightly CI; injected-delay attribution test kept permanently.
- **Perf**: 3-run median per §7.4 flake-tolerance rules; B9 per-PR; bundle analyzer per merge to `main`.
- **E2E**: a Playwright check that input is accepted immediately after `workspace_ready`.
- Coverage ≥80 % frontend on changed lines.

## Security notes
Startup timing and phase reports include the restored workspace's symbol list, which is user data but not secret. Auth/session restore is one of the measured phases — the harness must never log session tokens or the restored credential material, only phase durations. Confirm the harness's log output against the redaction allow-list from US-OBS-003 ("secrets, keys and tokens are never present in any log at any level, enforced by a serialiser allow-list and verified by a CI test").

## Accessibility notes
`workspace_ready` should coincide with the app being usable by keyboard and by a screen reader, not just by mouse: the ready predicate includes input acceptance, and the E2E check should exercise a keyboard input specifically. Any startup optimisation that defers the DOM-mirror or focus management past `workspace_ready` is not acceptable.

## Performance notes
Binding: budget #10 ≤3 s cold start (hard, reference hardware); budget #9 ≤8 MB gzipped initial bundle (soft, >+10 % vs baseline fails); B9 ≤900 ms engine cold init, ≤5 ms SDF atlas from cache.

## Observability
Emits a `startup_phase_seconds{phase}` histogram through the pushed-frontend-metrics path so field startup regressions are visible, plus the `workspace_ready` duration as a single recorded value per launch.

## Definition of Done
- [ ] All five Gherkin scenarios verified.
- [ ] `workspace_ready` definition written into `docs/plan/06-performance-and-load-standard.md` §2 budget-#10 row via a reviewed docs PR.
- [ ] Per-phase report emitted in the E46-T01 report schema; injected-delay attribution test permanent.
- [ ] CI baseline (CI runner) and reference-hardware manual number both recorded; cold-vs-warm stated explicitly.
- [ ] Bundle-size step wired and baselined.
- [ ] Before/after numbers in the PR for any optimisation made.
- [ ] Coverage ≥80 % frontend on changed lines; B9 green.

## Dependencies
- **E46-T01** for the shared report schema and baseline file format.

## Branch
`feat/e46-perf-startup`. PR size ≤400 LOC; harness and optimisations in separate PRs.

## References
`docs/plan/06-performance-and-load-standard.md` §2 budgets #9 and #10, §3.1, §7.4, §9 · `docs/plan/26-chart-engine-design.md` §13 (B9) · `docs/plan/23-ws-protocol.md` §5 · `docs/plan/11-user-stories.md` US-OBS-003, US-CHART-010
"""))
