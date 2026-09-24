# -*- coding: utf-8 -*-
"""E46 part 4: user-facing stories (SCR-046 diagnostics overlay, SCR-118 perf settings)."""
from _e46_lib import T

tickets = []

tickets.append(T("E46-S01", "Story",
    "Complete the SCR-046 engine diagnostics overlay with the stage table and WS-to-pixel latency",
    ["type/feature", "area/chart-engine", "priority/p2", "perf", "a11y", "design-qa", "qa"],
    "web", "Sprint 24", "P2 Medium", "Development", "R2 Render performance", 5, "E46",
    ["E46-D01", "E46-T01", "E46-T04", "E11", "E04"],
    """## Context
US-OBS-002 (Must, `docs/plan/11-user-stories.md` §28) has three scenarios; two of them (per-stage end-to-end measurement, budget-breach alerting) are owned by E46-T01 and E46-T04. The third — *"a compact latency indicator is available in the UI showing the current end-to-end figure"* — has no home until this Story. US-SET-008 (Should, §27) additionally requires that *"measured frame time and CPU/GPU load before and after are displayed"* when a performance profile changes, with the NFR *"measurements come from real frame instrumentation, not estimates"* — which is precisely what E46-T01 now emits.

SCR-046 (`docs/plan/14-screens-catalogue.md`) already exists in skeleton form from the chart-engine epics: it shows FPS, frame time p50/p95, draw calls, GPU memory, buffer uploads/s, WS message rate and dropped frames. Its design sign-off checklist names four things that are **not** yet built: the full per-stage breakdown implied by `docs/plan/06-performance-and-load-standard.md` §4.3, the **WS→pixel latency** figure, threshold colouring **paired with text** ("below budget"), and the **copy-diagnostics** control used in bug reports. This Story completes the screen against E46-D01's signed-off design.

The screen is the human face of the whole epic: when a budget is breached in the field, this overlay is the first thing the Owner opens, and it must name the stage rather than just show a bad number — the same stage-attribution principle the profiling playbook (§8) mandates for engineers.

Plan references: `docs/plan/14-screens-catalogue.md` SCR-046 · `docs/plan/18-traceability-matrix.md` (SCR-046 → US-SET-008, US-OBS-002; CMP-024, CMP-036, CMP-069, CMP-178) · `docs/plan/06-performance-and-load-standard.md` §2, §4.3, §5.1 · `docs/plan/20-architecture.md` §12.1 · `docs/plan/05-accessibility-standard.md`.

## Scope / Deliverables
- **Screen**: SCR-046 Chart engine diagnostics overlay, completed. Toggle stays `Ctrl+Shift+D`, hidden by default, and remains enableable from SCR-118 (E46-S02) per the catalogue entry.
- **Components** (all existing, from `docs/plan/15-component-catalogue.md` — no new design-system atoms): CMP-024 Sparkline (rolling frame-time and latency trends), CMP-036 KeyValueRow (`dt`/`dd` pairs for every metric), CMP-069 InfoPanel (the "what does this number mean" methodology drawer per stage), CMP-178 SystemHealthTile (the headline FPS / latency / GPU-memory tiles with `tone: ok|warning|danger`).
- **Stage table**: one row per the nine stages of `06-…` §4.3 (`input`, `data_window`, `bar_geometry`, `footprint_text`, `heatmap_upload`, `pane_redraw`, `overlay_redraw`, `dom_mirror`, `composite`), each showing p50/p95 measured, the documented slice, and a pass/fail state. Data source is the 2 Hz stage snapshot posted by E46-T01 on the existing stats channel.
- **WS→pixel latency**: the end-to-end figure required by US-OBS-002, computed from the ingestion-receipt timestamp propagated in the outbound WS envelope by E46-T04 (`docs/plan/23-ws-protocol.md` §3.1) versus the `requestAnimationFrame` paint timestamp, shown as current / p95 / p99 with the four backend stage values (`ingest_parse`, `book_update`, `pre_aggregate`, `fanout_emit`) broken out beneath it.
- **Compact latency indicator**: a small always-available readout (status-bar affordance, not the full overlay) showing the current end-to-end WS→pixel figure with a tone derived from budget #3 (green <100 ms p95, warning <250 ms, danger above), satisfying US-OBS-002 scenario 3. Visible without opening the overlay; opening the overlay is the drill-down.
- **Threshold colouring paired with text**: every toned value carries a text qualifier ("below budget" / "at budget" / "over budget") so tone is never the sole carrier of meaning.
- **Copy diagnostics**: a control that copies a redacted JSON snapshot (build hash from `GET /system/build`, GPU/renderer string, settings from SCR-118, the stage table, latency percentiles, dropped-frame count, degradation-ladder state) to the clipboard for pasting into a bug report.
- **Analytics**: emit `diagnostics.overlay_toggled` and `diagnostics.snapshot_copied` per the catalogue entry.
- **Degradation state**: surface which rungs of the `06-…` §4.4 ladder are currently engaged, with the non-colour-only "reduced live detail" wording.

## Out of scope
- Producing the measurements (E46-T01 frontend stages, E46-T04 backend stages) — this Story only renders what they emit.
- SCR-118 settings, the benchmark action and the recommended preset (E46-S02).
- SCR-143 admin system health and SCR-147 rate limits — owned by the admin epic (E42); this Story does not change them.
- Alerting on budget breach (E46-T04 owns the alert rule); the overlay shows state, it does not notify.
- Any new design-system component.

## Acceptance criteria
```gherkin
Scenario: The overlay names the stage that is over budget
  Given the engine is running a 4-pane workspace and the footprint text stage is exceeding its 4ms slice
  When I press Ctrl+Shift+D to open the diagnostics overlay
  Then a row for footprint_text shows its measured p50 and p95 against the 4ms documented slice
  And that row is marked "over budget" in text, not by colour alone
  And the eight other stages from docs/plan/06-performance-and-load-standard.md §4.3 are each present with their own measured values

Scenario: The compact latency indicator shows the end-to-end figure
  Given live market data is streaming and the overlay is closed
  Then a compact indicator displays the current WS-to-pixel latency in milliseconds
  And when I open the overlay, the same figure is broken down into ingest_parse, book_update, pre_aggregate, fanout_emit, network and client-render components

Scenario: Copy diagnostics produces a paste-ready redacted snapshot
  When I activate "copy diagnostics"
  Then the clipboard contains a JSON snapshot including build hash, GPU string, current settings, the stage table and latency percentiles
  And it contains no session token, API key, account id or order identifier
  And diagnostics.snapshot_copied is emitted

Scenario: No data yet
  Given the overlay is opened within the first two seconds of launch, before any stage snapshot has arrived
  Then each metric shows an explicit "measuring…" state rather than a zero or a dash
  And the overlay does not render a misleading 0ms frame time

Scenario: The overlay does not itself break the budget
  Given the overlay is pinned open for 10 minutes during a realistic-peak workload
  Then its measured cost is at or below 0.5ms per frame per the SCR-046 catalogue entry
  And it re-renders at 2Hz, not per frame

Scenario: Degradation is stated honestly
  Given the engine has engaged rung 4 of the docs/plan/06-performance-and-load-standard.md §4.4 degradation ladder
  Then the overlay states that background panes are showing reduced live detail, in text
  And the compact indicator reflects the degraded state
```

## Technical notes / design
Data flow: worker render loop → E46-T01 stage ring buffer → 2 Hz `stats` message on the existing worker stats channel → a React store slice → overlay. The overlay subscribes to that slice only; it must **not** subscribe to any per-tick market stream, or it becomes the thing it is measuring.

Rendering discipline: the overlay is a plain DOM text panel (explicitly *not* a canvas, per the catalogue a11y note), memoised per metric row, updating at the 2 Hz snapshot rate. Rows are keyed by the closed stage enum so React reconciliation is stable and no row remounts on update.

WS→pixel computation: `paint_ts − envelope.ingest_ts − clock_offset`, where `clock_offset` is the backend/frontend offset maintained per US-MKT-009's clock-sync mechanism (cited by US-OBS-002's NFR "clock offset accounted for per US-MKT-009"). If the offset is unknown or stale, the indicator shows "unavailable" rather than a number computed from an unsynchronised clock — a confidently wrong latency figure is worse than an honest gap.

Redaction for copy-diagnostics: build the snapshot from an explicit allow-list of field names, never by serialising an app-state object and removing keys. This mirrors the serialiser allow-list rule in US-OBS-003 and is the control E46-X02 reviews.

Percentiles are computed upstream by E46-T01; the overlay does no statistics of its own beyond formatting.

## Test plan
- **Unit**: stage-row formatting (measured vs slice vs verdict text) for over/at/under-budget; "measuring…" state when the snapshot is absent; latency "unavailable" when the clock offset is stale; snapshot builder emits exactly the allow-listed keys (table-driven, including a test that adds a secret-shaped key to the source state and asserts it is absent from the output); tone→text mapping is total over the enum.
- **Component/Storybook**: SCR-046 in states — measuring, all-green, one-stage-over, degraded-rung-4, clock-offset-unavailable. Visual regression on each.
- **Integration**: fake stats channel driving the overlay at 2 Hz for 60 s; assert exactly 120 re-renders (±2) and no per-frame render.
- **E2E (Playwright)**: open with `Ctrl+Shift+D`; assert all nine stage rows present; inject a synthetic slow stage via the test hook and assert the correct row reads "over budget"; activate copy-diagnostics and assert clipboard contents against the allow-list; assert the overlay is reachable and operable by keyboard only.
- **Perf**: measure overlay cost with the E46-T01 harness, overlay-closed vs overlay-pinned, on the B5 scenario; assert ≤0.5 ms/frame delta.
- **a11y**: axe-core on the open overlay; manual NVDA/VoiceOver pass confirming values announce politely (`aria-live="polite"`) and that the pinned overlay reads as a static table; keyboard-only open/close/copy.
- **Coverage**: ≥80 % frontend on changed lines.

## Security notes
Threats (STRIDE, per `docs/plan/04-security-program.md`; modelled in E46-X01): **Information disclosure** is the primary one — the snapshot is explicitly designed to be pasted into an issue tracker, so anything it contains must be assumed public. GPU/driver strings are fingerprinting material and are included deliberately (they are needed for support) but nothing account- or order-derived may be. Timing values are a side channel in principle; at this product's threat model (single owner + a few managers on Tailscale, no untrusted users) the residual risk is accepted and recorded, not mitigated by blurring the numbers. **Tampering**: the overlay is read-only and must expose no control that mutates engine state. Data classification: operational telemetry (internal), with the allow-list ensuring no Confidential field crosses into it. Requires the `security` review label via E46-X02.

## Accessibility notes
WCAG 2.2 AA, no exception (`docs/plan/02-definition-of-ready-done.md` §8). Specifics: the overlay is a text panel with definition-list semantics via CMP-036; live regions are `polite` and coalesced at 2 Hz so a screen reader is not flooded (catalogue requirement); it can be pinned and read as a static table; every toned value pairs tone with text ("over budget"), satisfying the colour-independence rule in `docs/plan/05-accessibility-standard.md`; `Ctrl+Shift+D` toggle is reachable from the command palette for users who cannot chord; focus moves into the overlay on open and returns to the prior element on close; contrast of all tone colours ≥4.5:1 against the overlay surface.

## Performance notes
Budget: ≤0.5 ms/frame overlay cost, 2 Hz sample rate (SCR-046 catalogue entry). The overlay must not allocate per frame. Budget #3 (WS→screen p95 <100 ms / p99 <250 ms) is the threshold source for the compact indicator's tones; budget #1 (16.6 ms) and the §4.3 slices are the thresholds for the stage table.

## Observability
Emits `diagnostics.overlay_toggled` and `diagnostics.snapshot_copied` analytics events. Consumes (does not define) `fe_frame_time_ms{stage}`, `fe_dropped_frames_total`, `fe_gpu_memory_mb`. No new metric is defined by this Story.

## Definition of Done
- [ ] All six Gherkin scenarios pass with automated tests referencing the scenario name.
- [ ] Design sign-off: built screen matches E46-D01's spec; SCR-046's four-item design checklist in `docs/plan/14-screens-catalogue.md` fully satisfied; `design-qa` reviewer comment posted.
- [ ] a11y: axe-core green; manual screen-reader pass recorded; keyboard-only path verified.
- [ ] perf: overlay cost measured and recorded in the PR (closed vs pinned).
- [ ] Security: copy-diagnostics allow-list reviewed by the Security engineer (E46-X02).
- [ ] Storybook entries for all five states; visual regression baselines committed.
- [ ] Coverage ≥80 % frontend on changed lines.
- [ ] `docs/plan/14-screens-catalogue.md` SCR-046 updated if the built screen diverged from the entry.
- [ ] QA sign-off with pass/fail per scenario; demoed at Sprint Review.

## Dependencies
- **E46-D01** — design must be Done ≥2 sprints before this Story starts (design-ahead rule, `02-definition-of-ready-done.md` §3.1). D01 is Sprint 21, this is Sprint 24.
- **E46-T01** — supplies the nine-stage 2 Hz snapshot and the percentile computation; without it there is nothing to render.
- **E46-T04** — supplies the ingestion-receipt timestamp and the four backend stage values in the WS envelope.
- **E11** (chart engine core) owns SCR-046's existing skeleton and the stats channel; **E04** owns the metrics pipeline.

## Branch
`feat/e46-perf-diagnostics-overlay`. PR size ≤400 LOC; split the compact latency indicator into its own PR if the overlay PR grows past that.

## References
`docs/plan/14-screens-catalogue.md` SCR-046 · `docs/plan/15-component-catalogue.md` CMP-024, CMP-036, CMP-069, CMP-178 · `docs/plan/18-traceability-matrix.md` (SCR-046 row) · `docs/plan/11-user-stories.md` US-OBS-002, US-SET-008, US-OBS-003, US-MKT-009 · `docs/plan/06-performance-and-load-standard.md` §2, §4.3, §4.4, §5.1 · `docs/plan/05-accessibility-standard.md` · `docs/plan/20-architecture.md` §12.1 · `docs/plan/22-api-openapi.yaml` `/system/build`
"""))

tickets.append(T("E46-S02", "Story",
    "Add the SCR-118 benchmark action and the recommended-for-this-machine performance preset",
    ["type/feature", "area/chart-engine", "priority/p2", "perf", "a11y", "design-qa", "qa"],
    "web", "Sprint 24", "P2 Medium", "Development", "R2 Render performance", 5, "E46",
    ["E46-D02", "E46-T01", "E46-T09", "E11"],
    """## Context
SCR-118 "Data & performance settings" (`docs/plan/14-screens-catalogue.md`) is the screen that governs the client-side performance budget: renderer selection, FPS cap, max bars in memory, heatmap trail ceiling, book depth default, panel update coalescing and cache size. Its design sign-off checklist requires six things, three of which do not exist yet: a **Run benchmark** action that measures FPS on a synthetic footprint+heatmap scene and stores the result for support, a **"recommended for this machine" preset derived from that benchmark**, and the **warning shown when the configured panel count exceeds the GPU budget**.

US-SET-008 (Should) makes the same demand from the user's side: profiles (maximum fidelity / balanced / low power) must set heatmap cadence, depth tier, bubble limits, sparkline usage and animation; changing a profile must display *measured* frame time and CPU/GPU load before and after; and when sustained frame times exceed the budget, a profile change is **suggested, never applied without consent** (except the automatic load-shedding of US-DOM-005, which is a different, already-built mechanism). Its NFR is unambiguous: *"measurements come from real frame instrumentation, not estimates."* E46-T01 makes that instrumentation available; this Story spends it.

This is the epic's user-visible safety valve: the budgets in `06-performance-and-load-standard.md` are set for the reference hardware of §3.1, and any machine weaker than that needs a principled, measured way to trade fidelity for frames instead of guessing.

## Scope / Deliverables
- **Screen**: SCR-118, completing its design checklist against E46-D02's signed-off spec.
- **Components** (existing only): CMP-004 Toggle, CMP-010 Slider, CMP-036 KeyValueRow, CMP-065 FormSection, CMP-086 SettingsNav/SettingsLayout, CMP-178 SystemHealthTile.
- **Run benchmark**: a synthetic scene (footprint at realistic cell density + 200-depth heatmap at 100 ms cadence + candles, mirroring the `packages/chart-engine/bench` B5 scenario referenced in `docs/plan/26-chart-engine-design.md` §13) run for a bounded, fixed duration, reported via the E46-T01 stage report so the on-screen result and the CI harness speak the same language. States per the catalogue: *benchmark running* · *results with a pass/fail against the minimum target* · *GPU blacklisted*.
- **Recommended preset**: a deterministic mapping from benchmark result → one of the three US-SET-008 profiles (maximum fidelity / balanced / low power) plus concrete per-control values (heatmap cadence, depth tier, bubble limit, FPS cap, max concurrent GPU panels, sparkline usage, animation). The mapping is a documented table, not a heuristic buried in code, and is shown to the user with its reasoning ("measured 38 fps on the footprint+heatmap scene → balanced").
- **Apply / reset**: "Apply recommended" and "Reset to recommended" actions. Nothing is applied without an explicit action — the automatic-suggestion scenario of US-SET-008 shows a dismissible suggestion, never a silent change.
- **Measured-value display**: every budget control shows its default, its range and its **current measured value** beside the target, per the catalogue a11y note ("Chart FPS cap: 60. Measured: 59."), sourced from live E46-T01 stage data.
- **Before/after report**: after applying a profile, show measured frame time and GPU-memory before vs after over a short settling window, satisfying US-SET-008 scenario 2.
- **Panel-count warning**: the catalogue-required warning when the configured max concurrent GPU panels exceeds what the measured GPU memory supports, stating the consequence.
- **Rebuild notice**: controls whose change requires a panel rebuild say so before applying (catalogue performance note).
- **Result persistence**: store the last benchmark result with the user's settings so support can correlate a reported FPS with a configuration; include it in SCR-046's copy-diagnostics snapshot (E46-S01) and in the SCR-119 support bundle.
- **Analytics**: `performance.setting_changed {key, before, after}` plus the diagnostics record, per the catalogue entry.

## Out of scope
- The diagnostics overlay itself (E46-S01) — this screen only links to it and toggles it.
- The automatic load-shedding ladder (`06-…` §4.4 / US-DOM-005) — already built; this Story surfaces its state, it does not change its policy.
- Recording/retention controls on SCR-118 that belong to US-REC-004 (E16) — untouched.
- Server-side or per-account performance settings; SCR-118 is per-machine, stored locally.
- Startup-time optimisation (E46-T09) — this Story consumes T09's startup benchmark hook, it does not optimise startup.

## Acceptance criteria
```gherkin
Scenario: Benchmark produces a real, bounded measurement
  Given I am on SCR-118 and activate "Run benchmark"
  When the synthetic footprint plus heatmap scene runs
  Then progress is shown while it runs and the action cannot be started twice
  And within a bounded, stated duration a result appears with measured p50 and p95 frame time and a pass or fail against the minimum target
  And the result comes from the engine stage instrumentation, not from an estimate

Scenario: The recommended preset is derived and explained
  Given a benchmark result of 38fps p50 on the synthetic scene
  Then the recommended profile is "balanced"
  And the reasoning is stated in text alongside it
  And the specific values it would set for heatmap cadence, depth tier, bubble limit, FPS cap and panel count are listed before I apply it

Scenario: Nothing changes without consent
  Given sustained frame times exceed the budget during normal use
  Then a suggestion to change profile appears
  And no setting changes until I explicitly accept
  And dismissing the suggestion does not re-prompt within the same session

Scenario: Before and after are measured, not claimed
  Given I apply the "low power" profile
  Then measured frame time and GPU memory from before the change and after a settling window are displayed side by side

Scenario: GPU is blacklisted
  Given the detected GPU driver is on the known-issue list
  Then the renderer control shows that software rendering is enabled and why
  And "Run benchmark" still works and its result is labelled as software-rendered

Scenario: Panel count exceeds the GPU budget
  Given I raise max concurrent GPU panels above what the measured GPU memory supports
  Then a warning states the consequence before the value is applied
  And the warning is conveyed in text, not by colour alone

Scenario: Benchmark fails to start
  Given the WebGL context cannot be created for the synthetic scene
  Then an explicit error names the cause and links to the renderer setting
  And no partial or fabricated result is stored
```

## Technical notes / design
The benchmark reuses the engine's existing bench scene definition rather than defining a second one — a divergence between "what the app measures" and "what CI measures" would make field reports uncomparable to CI baselines, which is the whole point of storing the result. The scene id and the E46-T01 report `schema` version are both stored with the result.

Recommendation mapping (documented table, committed alongside the code and referenced from `docs/plan/06-performance-and-load-standard.md`):

```
p50 frame time on the synthetic scene   → profile
  ≤16.6ms  (≥60fps)                     → maximum fidelity
  >16.6ms and ≤26ms (≥38fps)            → balanced
  >26ms and ≤33.3ms (≥30fps)            → low power
  >33.3ms (<30fps)                      → low power + a warning that the machine is below the documented minimum
```
Ties and boundary values resolve to the *more conservative* profile. The table is data, unit-tested at every boundary.

Benchmark run is time-boxed (a fixed warm-up discarded, then a fixed measurement window) and cancellable; it must not be run while replay is active or while an order ticket is open, and the action is disabled with a stated reason in those cases (`disabledReason` is a first-class CMP prop in this design system).

Persistence is local-only (per-machine settings store), never synced to another user's machine; it is included in support artefacts by value, not by reference.

Error codes surfaced: WebGL context creation failure, benchmark cancelled, benchmark timed out. Each has its own message; none silently produces a result.

## Test plan
- **Unit**: the recommendation mapping at every boundary value including exact ties (16.6, 26, 33.3) and the below-minimum case; settings→profile application is total over the control set; before/after report formatting; `disabledReason` logic for replay-active and ticket-open; result persistence round-trip.
- **Component/Storybook**: SCR-118 in states — idle, benchmark running, result pass, result fail, GPU blacklisted, panel-count warning, suggestion banner shown/dismissed. Visual regression on each.
- **Integration**: drive the benchmark against a stubbed engine returning scripted stage reports; assert the correct profile is recommended and that no setting mutates before "apply".
- **E2E (Playwright)**: run the benchmark end to end in Electron; assert a bounded run time, a stored result, that applying the preset changes the named settings and that the before/after panel populates; assert the suggestion never auto-applies; keyboard-only traversal of every control.
- **Perf**: the benchmark itself must not leak — run it 20× consecutively and assert GPU memory and JS heap return to baseline (ties to E46-T06's leak criteria).
- **a11y**: axe-core; manual screen-reader pass over the grouped controls asserting that units and measured values are announced with their labels; `aria-busy` during the run; result announced politely on completion.
- **Coverage**: ≥80 % frontend on changed lines.

## Security notes
Threats (E46-X01 STRIDE): **Information disclosure** — the stored benchmark result carries GPU/driver strings and settings, and flows into the support bundle (US-OBS-007) and the SCR-046 snapshot; US-OBS-007 already requires the bundle to be secret-scanned before writing, and this Story must not add any field that would defeat that (no symbol lists, no account ids in the result record). **Denial of service (self-inflicted)** — "Run benchmark" is a deliberate heavy GPU workload; it must be rate-limited to one concurrent run, must be blocked while trading-critical surfaces are active, and must be cancellable, so it can never be used (or mis-clicked) into starving the trading path. **Tampering** — the local settings store is user-writable by definition; the app must validate ranges on read and fall back to documented defaults on a malformed value rather than trusting the stored number. Data classification: local operational settings (internal). Reviewed under E46-X02.

## Accessibility notes
WCAG 2.2 AA. Per the SCR-118 catalogue a11y note: grouped numeric and toggle controls (CMP-065 `fieldset`/`legend`) with units *and* current measured values announced beside each target; the diagnostics toggle's label explains what SCR-046 shows. Sliders (CMP-010) expose `aria-valuetext` with the unit, not a bare number. The running benchmark sets `aria-busy` and announces completion politely; a long run must not trap focus. The panel-count warning and the pass/fail result are text-first. Reduced-motion is honoured by the benchmark's own scene (it is a measurement, and it is announced as such, but no unnecessary animation is added to the surrounding UI).

## Performance notes
The benchmark measures against budget #1 (≤16.6 ms p95) and the 30 fps floor of budget #2. Its scene must match the B5 bench scenario in `docs/plan/26-chart-engine-design.md` §13. The settings screen itself is a normal form and carries no special frame budget, but it must not subscribe to per-tick data to render its "measured" values — it reads the same 2 Hz snapshot as SCR-046.

## Observability
Emits `performance.setting_changed {key, before, after}` (analytics) plus a diagnostics record so a support report can be correlated with the configuration that produced it. Benchmark results are stored locally and included in the support bundle; no new server-side metric.

## Definition of Done
- [ ] All seven Gherkin scenarios pass with automated tests referencing the scenario name.
- [ ] Design sign-off: SCR-118's six-item design checklist in `docs/plan/14-screens-catalogue.md` fully satisfied; `design-qa` reviewer comment posted.
- [ ] Recommendation mapping table committed as data, unit-tested at every boundary, and cross-referenced from `docs/plan/06-performance-and-load-standard.md`.
- [ ] a11y: axe-core green; manual screen-reader pass recorded; keyboard-only path verified.
- [ ] perf: 20× consecutive benchmark leak check green.
- [ ] Security: benchmark-result field list reviewed against the support-bundle redaction rules (E46-X02).
- [ ] Storybook entries for all seven states; visual regression baselines committed.
- [ ] Coverage ≥80 % frontend on changed lines.
- [ ] QA sign-off with pass/fail per scenario; demoed at Sprint Review.

## Dependencies
- **E46-D02** — design Done ≥2 sprints ahead (Sprint 21 → this Story Sprint 24).
- **E46-T01** — the stage instrumentation and report schema the benchmark and the "measured" values both read.
- **E46-T09** — supplies the startup benchmark hook the catalogue's "recommended preset derived from a startup benchmark" phrasing refers to, and shares the bundle-size/startup reporting path.
- **E11** — owns the engine bench scene being reused and SCR-118's existing controls.

## Branch
`feat/e46-perf-settings-benchmark`. PR size ≤400 LOC; land the benchmark runner and the recommendation/preset UI as two PRs.

## References
`docs/plan/14-screens-catalogue.md` SCR-118, SCR-119 · `docs/plan/15-component-catalogue.md` CMP-004, CMP-010, CMP-036, CMP-065, CMP-086, CMP-178 · `docs/plan/18-traceability-matrix.md` (SCR-118 row, US-SET-008 row) · `docs/plan/11-user-stories.md` US-SET-008, US-DOM-005, US-OBS-007, US-CHART-010 · `docs/plan/06-performance-and-load-standard.md` §2 budgets #1/#2/#7, §3.1, §4.4 · `docs/plan/26-chart-engine-design.md` §11, §13 · `docs/plan/05-accessibility-standard.md`
"""))
